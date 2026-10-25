# -*- coding: utf-8 -*-
"""Réclamation à l'arrivée : poids débarqué et qualité, par BL.

Les contrats de fèves se règlent souvent sur le poids DÉBARQUÉ : l'acheteur
fait peser la marchandise au port d'arrivée et réclame la perte au-delà
d'une franchise (0,5 % par défaut, réglable). Une expertise ou un arbitrage
peut aussi aboutir à une réfaction pour qualité.

  perte (kg)        = net embarqué − net débarqué (si positive)
  franchise (kg)    = net embarqué × franchise %
  perte réclamable  = perte − franchise (si positive)
  montant poids     = perte réclamable × prix unitaire de la facture
  montant réclamé   = montant poids + montant qualité

Le montant ACCORDÉ (négocié) se règle par un avoir sur la facture du BL —
assistant d'avoir du socle — ou par une pièce du logiciel comptable (la
comptabilité est tenue hors d'Odoo : on en reporte la référence).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round

PARAM_FRANCHISE = 'cocoa_bean_export.weight_franchise_pct'
DEFAULT_FRANCHISE = 0.5


class CocoaBeanExportClaim(models.Model):
    _name = 'cocoa.bean.export.claim'
    _description = "Réclamation à l'arrivée (fèves)"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string="Référence", required=True, copy=False, readonly=True,
                       default=lambda self: _("Nouveau"))
    state = fields.Selection([
        ('draft', "Brouillon"),
        ('submitted', "Présentée par l'acheteur"),
        ('agreed', "Accordée"),
        ('settled', "Réglée"),
        ('rejected', "Rejetée"),
        ('cancelled', "Annulée"),
    ], string="État", default='draft', required=True, tracking=True, copy=False, index=True)
    delivery_note_id = fields.Many2one(
        'potting.delivery.note', string="BL", required=True, tracking=True,
        check_company=True, domain="[('product_type', '=', 'cocoa_beans')]")
    company_id = fields.Many2one(related='delivery_note_id.company_id', store=True)
    transit_order_id = fields.Many2one(related='delivery_note_id.transit_order_id', store=True)
    customer_id = fields.Many2one(related='delivery_note_id.customer_id', store=True,
                                  string="Acheteur")
    invoice_id = fields.Many2one(
        'potting.customer.invoice', string="Facture", tracking=True, check_company=True,
        domain="[('invoice_type', '=', 'invoice'), ('state', 'in', ('confirmed', 'sent')), "
               "('transit_order_id', '=', transit_order_id)]",
        help="Facture sur laquelle porte la réclamation (et l'avoir éventuel).")
    currency_id = fields.Many2one('res.currency', string="Devise", required=True,
                                  default=lambda self: self.env.company.currency_id)
    claim_date = fields.Date(string="Reçue le", default=fields.Date.context_today,
                             tracking=True)

    # --- Poids ---------------------------------------------------------------
    shipped_net_kg = fields.Float(string="Net embarqué (kg)", digits=(16, 2),
                                  tracking=True)
    landed_net_kg = fields.Float(string="Net débarqué (kg)", digits=(16, 2), tracking=True,
                                 help="Certificat de poids à l'arrivée.")
    landed_weight_ref = fields.Char(string="Certificat de poids à l'arrivée")
    franchise_pct = fields.Float(
        string="Franchise (%)", digits=(5, 3), tracking=True,
        default=lambda self: self._default_franchise(),
        help="Perte de poids admise sans réclamation (réglage : Paramètres ▸ "
             "Export des fèves).")
    weight_loss_kg = fields.Float(string="Perte (kg)", digits=(16, 2),
                                  compute='_compute_amounts', store=True)
    franchise_kg = fields.Float(string="Franchise (kg)", digits=(16, 2),
                                compute='_compute_amounts', store=True)
    claimable_kg = fields.Float(string="Perte réclamable (kg)", digits=(16, 2),
                                compute='_compute_amounts', store=True)
    unit_price_kg = fields.Float(
        string="Prix unitaire (/kg)", digits=(16, 4), tracking=True,
        help="Prix de la facture ramené au kg (montant ÷ tonnage facturé).")
    weight_claim_amount = fields.Monetary(string="Montant poids",
                                          compute='_compute_amounts', store=True)

    # --- Qualité -------------------------------------------------------------
    quality_claim_amount = fields.Monetary(string="Montant qualité", tracking=True)
    quality_reason = fields.Text(string="Motif qualité",
                                 help="Constat d'expertise ou décision d'arbitrage.")
    survey_ref = fields.Char(string="Rapport d'expertise / arbitrage")

    # --- Montants et règlement ------------------------------------------------
    claimed_amount = fields.Monetary(string="Montant réclamé",
                                     compute='_compute_amounts', store=True)
    agreed_amount = fields.Monetary(string="Montant accordé", tracking=True)
    settlement_mode = fields.Selection([
        ('credit_note', "Avoir sur la facture"),
        ('accounting', "Pièce comptable externe"),
    ], string="Règlement", tracking=True)
    credit_note_id = fields.Many2one('potting.customer.invoice', string="Avoir",
                                     readonly=True, copy=False)
    accounting_ref = fields.Char(string="N° de pièce comptable", tracking=True, copy=False)
    accounting_date = fields.Date(string="Date de la pièce", copy=False)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'bean_export_claim_attachment_rel', 'claim_id', 'attachment_id',
        string="Pièces (certificats, expertises)")
    note = fields.Text(string="Notes")

    @api.model
    def _default_franchise(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_FRANCHISE)
        # Paramètre absent : get_param renvoie False, et float(False) vaut 0
        if raw in (None, False, ''):
            return DEFAULT_FRANCHISE
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_FRANCHISE
        return value if value >= 0 else DEFAULT_FRANCHISE

    @api.depends('shipped_net_kg', 'landed_net_kg', 'franchise_pct', 'unit_price_kg',
                 'quality_claim_amount')
    def _compute_amounts(self):
        for claim in self:
            loss = 0.0
            if claim.landed_net_kg:
                loss = max((claim.shipped_net_kg or 0.0) - claim.landed_net_kg, 0.0)
            franchise = (claim.shipped_net_kg or 0.0) * (claim.franchise_pct or 0.0) / 100.0
            claimable = max(loss - franchise, 0.0)
            claim.weight_loss_kg = float_round(loss, precision_digits=2)
            claim.franchise_kg = float_round(franchise, precision_digits=2)
            claim.claimable_kg = float_round(claimable, precision_digits=2)
            claim.weight_claim_amount = claim.currency_id.round(
                claimable * (claim.unit_price_kg or 0.0))
            claim.claimed_amount = claim.weight_claim_amount + (claim.quality_claim_amount or 0.0)

    @api.onchange('delivery_note_id')
    def _onchange_delivery_note_id(self):
        self._fill_from_delivery_note()

    def _fill_from_delivery_note(self):
        for claim in self:
            note = claim.delivery_note_id
            if not note:
                continue
            claim.shipped_net_kg = float_round(note.total_tonnage * 1000.0, precision_digits=2)
            invoice = note.customer_invoice_id.filtered(
                lambda i: i.invoice_type == 'invoice' and i.state in ('confirmed', 'sent'))
            if not invoice:
                invoice = note.transit_order_id.customer_invoice_ids.filtered(
                    lambda i: i.invoice_type == 'invoice' and i.state in ('confirmed', 'sent'))[:1]
            if invoice:
                claim.invoice_id = invoice
                claim.currency_id = invoice.currency_id
                if invoice.invoiced_tonnage:
                    claim.unit_price_kg = float_round(
                        invoice.amount_total / (invoice.invoiced_tonnage * 1000.0),
                        precision_digits=4)

    @api.constrains('landed_net_kg', 'shipped_net_kg', 'franchise_pct', 'agreed_amount',
                    'quality_claim_amount', 'unit_price_kg')
    def _check_values(self):
        for claim in self:
            if min(claim.landed_net_kg, claim.shipped_net_kg, claim.franchise_pct,
                   claim.agreed_amount, claim.quality_claim_amount, claim.unit_price_kg) < 0:
                raise ValidationError(_("Les poids, taux et montants ne peuvent pas être négatifs."))
            if claim.franchise_pct > 10:
                raise ValidationError(_("Une franchise de plus de 10 % est une erreur de saisie."))

    @api.constrains('delivery_note_id', 'state')
    def _check_one_open_claim(self):
        for claim in self.filtered(lambda c: c.state not in ('cancelled', 'rejected')):
            other = self.search([
                ('id', '!=', claim.id), ('delivery_note_id', '=', claim.delivery_note_id.id),
                ('state', 'not in', ('cancelled', 'rejected'))], limit=1)
            if other:
                raise ValidationError(_(
                    "Le BL %(bl)s a déjà une réclamation en cours (%(other)s).",
                    bl=claim.delivery_note_id.name, other=other.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _("Nouveau")) == _("Nouveau"):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'cocoa.bean.export.claim') or _("Nouveau")
        claims = super().create(vals_list)
        for claim, vals in zip(claims, vals_list):
            if not vals.get('shipped_net_kg'):
                claim._fill_from_delivery_note()
        return claims

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------
    def action_submit(self):
        for claim in self.filtered(lambda c: c.state == 'draft'):
            if float_is_zero(claim.claimed_amount, precision_digits=2):
                raise UserError(_(
                    "%s : rien n'est réclamé (perte sous la franchise et pas de "
                    "réfaction qualité).", claim.name))
            claim.write({'state': 'submitted',
                         'agreed_amount': claim.agreed_amount or claim.claimed_amount})
        return True

    def action_agree(self):
        self._check_manager()
        for claim in self.filtered(lambda c: c.state == 'submitted'):
            if float_is_zero(claim.agreed_amount, precision_digits=2):
                raise UserError(_("%s : indiquez le montant accordé.", claim.name))
            if float_compare(claim.agreed_amount, claim.claimed_amount, precision_digits=2) > 0:
                raise UserError(_(
                    "%s : le montant accordé dépasse le montant réclamé.", claim.name))
            claim.state = 'agreed'
        return True

    def action_reject(self):
        self._check_manager()
        self.filtered(lambda c: c.state in ('draft', 'submitted')).write({'state': 'rejected'})
        return True

    def action_cancel(self):
        if self.filtered(lambda c: c.state == 'settled'):
            raise UserError(_("Une réclamation réglée ne s'annule pas : annulez d'abord "
                              "l'avoir ou la pièce comptable."))
        self.write({'state': 'cancelled'})
        return True

    def action_draft(self):
        self.filtered(lambda c: c.state in ('submitted', 'rejected', 'cancelled')).write(
            {'state': 'draft'})
        return True

    def action_create_credit_note(self):
        """Avoir du montant accordé, par l'assistant d'avoir du socle."""
        self.ensure_one()
        self._check_manager()
        if self.state != 'agreed':
            raise UserError(_("Seule une réclamation accordée se règle."))
        if not self.invoice_id:
            raise UserError(_("Indiquez la facture sur laquelle porte la réclamation."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Avoir — réclamation %s", self.name),
            'res_model': 'potting.customer.credit.note.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_invoice_id': self.invoice_id.id,
                'default_mode': 'amount',
                'default_free_amount': self.agreed_amount,
                'default_reason': _("Réclamation à l'arrivée %(claim)s — BL %(bl)s",
                                    claim=self.name, bl=self.delivery_note_id.name),
                'bean_claim_id': self.id,
            },
        }

    def action_mark_settled_accounting(self):
        """Règlement hors avoir : reporter la pièce du logiciel comptable."""
        self._check_manager()
        for claim in self:
            if claim.state != 'agreed':
                raise UserError(_("Seule une réclamation accordée se règle."))
            if not (claim.accounting_ref or '').strip() or not claim.accounting_date:
                raise UserError(_("%s : renseignez le n° et la date de la pièce comptable.",
                                  claim.name))
            claim.write({'state': 'settled', 'settlement_mode': 'accounting'})
        return True

    def _settle_with_credit_note(self, credit_note):
        self.ensure_one()
        self.write({'state': 'settled', 'settlement_mode': 'credit_note',
                    'credit_note_id': credit_note.id})
        self.message_post(body=_("Réglée par l'avoir %s.", credit_note.name))

    def _check_manager(self):
        if not self.env.user.has_group('potting_management.group_potting_manager'):
            raise UserError(_("Seul un Manager accorde, rejette ou règle une réclamation."))


class PottingCustomerCreditNoteWizardClaim(models.TransientModel):
    _inherit = 'potting.customer.credit.note.wizard'

    def action_create(self):
        action = super().action_create()
        claim_id = self.env.context.get('bean_claim_id')
        if claim_id and action.get('res_id'):
            claim = self.env['cocoa.bean.export.claim'].browse(claim_id)
            credit_note = self.env['potting.customer.invoice'].browse(action['res_id'])
            claim._settle_with_credit_note(credit_note)
        return action


class PottingDeliveryNoteClaim(models.Model):
    _inherit = 'potting.delivery.note'

    bean_claim_ids = fields.One2many('cocoa.bean.export.claim', 'delivery_note_id',
                                     string="Réclamations à l'arrivée")
    bean_claim_count = fields.Integer(compute='_compute_bean_claim_count')

    @api.depends('bean_claim_ids')
    def _compute_bean_claim_count(self):
        for note in self:
            note.bean_claim_count = len(note.bean_claim_ids)

    def action_open_bean_claims(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _("Réclamations — %s", self.name),
            'res_model': 'cocoa.bean.export.claim',
            'view_mode': 'tree,form',
            'domain': [('delivery_note_id', '=', self.id)],
            'context': {'default_delivery_note_id': self.id},
        }
        if len(self.bean_claim_ids) == 1:
            action.update({'view_mode': 'form', 'res_id': self.bean_claim_ids.id})
        return action
