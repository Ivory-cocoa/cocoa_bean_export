# -*- coding: utf-8 -*-
"""Documents d'une expédition de fèves (certificats phytosanitaire, de
fumigation, d'origine, de qualité, de poids…).

La liste des documents et leur exigence sont des données de configuration
(Configuration ▸ Documents d'export des fèves) : rien n'est imposé par le
code. Chaque type dit à quel moment il est exigé — confirmation du BL ou
confirmation de la facture —, s'il faut joindre la pièce, et combien de
jours il reste valable (fumigation, phytosanitaire) par rapport à la date
d'embarquement.

Le contrôle est posé sur l'ÉCRITURE de l'état (BL « confirmé », facture
« confirmée ») et non sur un bouton : la confirmation unitaire, la
confirmation groupée et tout autre chemin passent par la même porte.
"""

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .product_spec import PRODUCT_TYPE

REQUIREMENTS = [
    ('optional', "Facultatif"),
    ('bl', "Exigé à la confirmation du BL"),
    ('invoice', "Exigé à la confirmation de la facture"),
]


class CocoaBeanExportDocumentType(models.Model):
    _name = 'cocoa.bean.export.document.type'
    _description = "Type de document d'export (fèves)"
    _order = 'sequence, id'

    name = fields.Char(string="Document", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    requirement = fields.Selection(
        REQUIREMENTS, string="Exigence", required=True, default='optional',
        help="Moment où le document doit être renseigné (n° et date).")
    requires_attachment = fields.Boolean(
        string="Pièce jointe exigée",
        help="Le document n'est complet qu'avec le scan joint.")
    validity_days = fields.Integer(
        string="Validité (jours)",
        help="0 : sans limite. Sinon le document doit être daté au plus tant "
             "de jours avant l'embarquement (ex. fumigation).")
    certified_only = fields.Boolean(
        string="Lots certifiés seulement",
        help="Exigé seulement si le BL porte des lots certifiés (certificat de "
             "transaction RA / Fairtrade…).")
    eu_only = fields.Boolean(
        string="Destination UE seulement",
        help="Exigé seulement pour une destination de l'Union européenne.")
    issuer = fields.Char(string="Émetteur habituel",
                         help="Ex. Ministère de l'Agriculture (DPVCQ), CCC, CCI-CI.")
    note = fields.Text(string="Notes")
    company_id = fields.Many2one('res.company', string="Société",
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)',
         "Ce code de document existe déjà."),
        ('validity_positive', 'CHECK(validity_days >= 0)',
         "La validité ne peut pas être négative."),
    ]

    def _applies_to(self, note):
        """Le type concerne-t-il ce BL (certification, destination) ?"""
        self.ensure_one()
        if self.certified_only and not note.lot_ids.filtered('certification_id'):
            return False
        if self.eu_only and not note._bean_export_is_european():
            return False
        return True


class CocoaBeanExportDocument(models.Model):
    _name = 'cocoa.bean.export.document'
    _description = "Document d'export d'un BL (fèves)"
    _order = 'sequence, id'
    _check_company_auto = True

    delivery_note_id = fields.Many2one(
        'potting.delivery.note', string="BL", required=True, ondelete='cascade',
        index=True)
    company_id = fields.Many2one(related='delivery_note_id.company_id', store=True)
    type_id = fields.Many2one(
        'cocoa.bean.export.document.type', string="Document", required=True,
        ondelete='restrict')
    sequence = fields.Integer(related='type_id.sequence', store=True)
    requirement = fields.Selection(related='type_id.requirement')
    number = fields.Char(string="Numéro")
    date = fields.Date(string="Date")
    issuer = fields.Char(string="Émetteur")
    attachment_ids = fields.Many2many(
        'ir.attachment', 'bean_export_document_attachment_rel', 'document_id',
        'attachment_id', string="Pièces")
    note = fields.Char(string="Observation")
    status = fields.Selection([
        ('missing', "Manquant"),
        ('incomplete', "Incomplet"),
        ('expired', "Hors validité"),
        ('ok', "Complet"),
    ], string="Statut", compute='_compute_status', store=True)
    status_detail = fields.Char(string="Détail", compute='_compute_status', store=True)

    _sql_constraints = [
        ('type_per_bl_uniq', 'unique(delivery_note_id, type_id)',
         "Ce document figure déjà sur le BL."),
    ]

    @api.depends('number', 'date', 'attachment_ids', 'type_id.requires_attachment',
                 'type_id.validity_days', 'delivery_note_id.date_shipment')
    def _compute_status(self):
        for doc in self:
            doc_type = doc.type_id
            if not doc.number and not doc.date:
                doc.status, doc.status_detail = 'missing', _("À renseigner")
                continue
            missing = []
            if not (doc.number or '').strip():
                missing.append(_("numéro"))
            if not doc.date:
                missing.append(_("date"))
            if doc_type.requires_attachment and not doc.attachment_ids:
                missing.append(_("pièce jointe"))
            if missing:
                doc.status = 'incomplete'
                doc.status_detail = _("Manque : %s", ", ".join(missing))
                continue
            shipment = doc.delivery_note_id.date_shipment
            if doc_type.validity_days and shipment and \
                    doc.date + timedelta(days=doc_type.validity_days) < shipment:
                doc.status = 'expired'
                doc.status_detail = _(
                    "Daté du %(date)s : plus de %(days)s j avant l'embarquement "
                    "(%(ship)s).", date=fields.Date.to_string(doc.date),
                    days=doc_type.validity_days, ship=fields.Date.to_string(shipment))
                continue
            doc.status, doc.status_detail = 'ok', False

    @api.constrains('date')
    def _check_date(self):
        today = fields.Date.context_today(self)
        for doc in self:
            if doc.date and doc.date > today:
                raise ValidationError(_(
                    "%s : un document ne peut pas être daté dans le futur.",
                    doc.type_id.name))


class PottingDeliveryNoteBeanDocuments(models.Model):
    _inherit = 'potting.delivery.note'

    bean_document_ids = fields.One2many(
        'cocoa.bean.export.document', 'delivery_note_id', string="Documents d'export")
    bean_documents_complete = fields.Boolean(
        string="Documents complets", compute='_compute_bean_documents')
    bean_documents_summary = fields.Char(
        string="Documents", compute='_compute_bean_documents')

    def _bean_export_is_european(self):
        self.ensure_one()
        country = self.pod_id.country_id
        return bool(country) and country._potting_is_european()

    @api.depends('bean_document_ids.status', 'lot_ids')
    def _compute_bean_documents(self):
        for note in self:
            if note.product_type != PRODUCT_TYPE:
                note.bean_documents_complete = True
                note.bean_documents_summary = False
                continue
            missing = note._bean_document_issues(('bl', 'invoice'))
            note.bean_documents_complete = not missing
            done = len(note.bean_document_ids.filtered(lambda d: d.status == 'ok'))
            note.bean_documents_summary = _(
                "%(done)s / %(total)s complets", done=done,
                total=len(note.bean_document_ids))

    def _bean_document_types(self):
        self.ensure_one()
        return self.env['cocoa.bean.export.document.type'].search([
            ('company_id', 'in', (False, self.company_id.id))])

    def _bean_document_issues(self, requirements):
        """Documents exigés (pour ces moments) non complets sur le BL."""
        self.ensure_one()
        issues = []
        for doc_type in self._bean_document_types().filtered(
                lambda t: t.requirement in requirements and t._applies_to(self)):
            doc = self.bean_document_ids.filtered(lambda d: d.type_id == doc_type)[:1]
            if not doc or doc.status == 'missing':
                issues.append(_("%s : manquant", doc_type.name))
            elif doc.status != 'ok':
                issues.append("%s : %s" % (doc_type.name, doc.status_detail))
        return issues

    def action_bean_documents_sync(self):
        """Ajoute une ligne par type de document actif qui manque au BL."""
        for note in self.filtered(lambda n: n.product_type == PRODUCT_TYPE):
            present = note.bean_document_ids.mapped('type_id')
            missing = note._bean_document_types().filtered(
                lambda t: t not in present and t._applies_to(note))
            if missing:
                note.write({'bean_document_ids': [
                    (0, 0, {'type_id': doc_type.id, 'issuer': doc_type.issuer})
                    for doc_type in missing]})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        notes = super().create(vals_list)
        notes.action_bean_documents_sync()
        return notes

    def write(self, vals):
        if vals.get('state') == 'confirmed' and not self.env.context.get(
                'skip_bean_document_check'):
            self._check_bean_documents(('bl',), _("confirmer le BL"))
        return super().write(vals)

    def _check_bean_documents(self, requirements, action_label):
        blocking = []
        for note in self.filtered(lambda n: n.product_type == PRODUCT_TYPE):
            note.action_bean_documents_sync()
            issues = note._bean_document_issues(requirements)
            if issues:
                blocking.append("%s :\n%s" % (note.name, "\n".join(
                    "  • " + issue for issue in issues)))
        if blocking:
            raise UserError(_(
                "📄 Documents d'export incomplets — impossible de %(action)s.\n\n"
                "%(issues)s\n\nRenseignez-les dans l'onglet « Documents d'export » "
                "du BL (la liste et les exigences se règlent dans Configuration ▸ "
                "Documents d'export des fèves).",
                action=action_label, issues="\n\n".join(blocking)))


class PottingCustomerInvoiceBeanDocuments(models.Model):
    _inherit = 'potting.customer.invoice'

    def _bean_delivery_notes(self):
        self.ensure_one()
        if self.delivery_note_id:
            return self.delivery_note_id
        return self.transit_order_id.delivery_note_ids.filtered(
            lambda n: n.state != 'cancelled')

    def write(self, vals):
        if vals.get('state') == 'confirmed' and not self.env.context.get(
                'skip_bean_document_check'):
            for invoice in self.filtered(lambda i: i.state == 'draft'
                                         and i.product_type == PRODUCT_TYPE):
                invoice._bean_delivery_notes()._check_bean_documents(
                    ('bl', 'invoice'), _("confirmer la facture %s", invoice.name))
        return super().write(vals)
