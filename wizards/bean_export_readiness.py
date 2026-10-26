# -*- coding: utf-8 -*-
"""Mise en service : la base est-elle prête pour un premier export de fèves ?

Chaque contrôle lit la configuration réelle (rien n'est déclaré « fait » à
la main) et renvoie un statut — bloquant, à compléter, conforme — avec le
détail et un bouton vers l'écran où corriger. Seuls les contrôles
bloquants empêchent de travailler : facture refusée faute de taux, lot sans
séquence, taxes CCC absentes…

Ajouter un contrôle : une méthode ``_check_<clé>`` qui renvoie
(statut, détail) et une entrée dans ``_CHECKS``.
"""

from datetime import timedelta

from odoo import _, api, fields, models

from ..models.product_spec import FAMILY_BEANS, FAMILY_GROUPS, FAMILY_SEMI_FINISHED

ERROR, WARNING, OK = 'error', 'warning', 'ok'
RATE_STALE_DAYS = 30


class CocoaBeanExportReadiness(models.TransientModel):
    _name = 'cocoa.bean.export.readiness'
    _description = "Mise en service de l'export des fèves"

    line_ids = fields.One2many('cocoa.bean.export.readiness.line', 'wizard_id',
                               string="Contrôles")
    error_count = fields.Integer(compute='_compute_counts')
    warning_count = fields.Integer(compute='_compute_counts')
    ok_count = fields.Integer(compute='_compute_counts')
    checked_at = fields.Datetime(string="Contrôlé le", readonly=True)

    # (clé, rubrique, intitulé, action de correction)
    _CHECKS = [
        ('company_identity', "Société", "Identité imprimée (nom, NCC, REX)",
         'potting_management.action_potting_config_settings'),
        ('company_bank', "Société", "Compte bancaire de la société (factures)",
         'base.action_res_partner_bank_account_form'),
        ('currency_rates', "Finance", "Taux de change des devises actives",
         'base.action_currency_form'),
        ('export_campaign', "Campagne", "Campagne export en cours",
         'potting_management.potting_campaign_action'),
        ('ccc_taxes', "Réglementation CCC", "Types de taxes CCC (redevances, DUS)",
         'potting_management.action_potting_taxe_type'),
        ('lot_sequence', "Numérotation", "Séquence des lots de fèves", 'base.ir_sequence_form'),
        ('sites', "Logistique", "Sites d'usinage", 'cocoa_bean_management.action_cocoa_reception_site'),
        ('ports', "Logistique", "Ports d'embarquement et de déchargement",
         'potting_management.action_potting_port'),
        ('forwarders', "Logistique", "Transitaires", 'potting_management.potting_forwarding_agent_action'),
        ('quality_standard', "Qualité", "Norme d'acceptation des fèves ordinaires",
         'cocoa_bean_management.action_cocoa_quality_standard'),
        ('grade_grid', "Qualité", "Grille des grades de la campagne fèves",
         'cocoa_bean_export.action_bean_export_grade_grid'),
        ('documents', "Documents", "Documents d'export exigés",
         'cocoa_bean_export.action_cocoa_bean_export_document_type'),
        ('managers', "Utilisateurs", "Managers Export", 'base.action_res_users'),
        ('scope', "Périmètre", "Produits exportés", 'potting_management.action_potting_config_settings'),
    ]

    @api.depends('line_ids.status')
    def _compute_counts(self):
        for wizard in self:
            statuses = wizard.line_ids.mapped('status')
            wizard.error_count = statuses.count(ERROR)
            wizard.warning_count = statuses.count(WARNING)
            wizard.ok_count = statuses.count(OK)

    @api.model
    def action_open(self):
        wizard = self.create({})
        wizard.action_refresh()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Mise en service — export des fèves"),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_refresh(self):
        self.ensure_one()
        lines = []
        for sequence, (key, section, label, action) in enumerate(self._CHECKS):
            try:
                status, detail = getattr(self, '_check_%s' % key)()
            except Exception as exc:  # un contrôle cassé ne doit pas masquer les autres
                status, detail = ERROR, _("Contrôle impossible : %s", exc)
            lines.append((0, 0, {'sequence': sequence, 'key': key, 'section': section,
                                 'name': label, 'status': status, 'detail': detail,
                                 'action_xmlid': action}))
        self.line_ids.unlink()
        self.write({'line_ids': lines, 'checked_at': fields.Datetime.now()})
        return True

    # ------------------------------------------------------------------
    # Contrôles : (statut, détail)
    # ------------------------------------------------------------------
    def _company(self):
        return self.env.company

    def _check_company_identity(self):
        company = self._company()
        missing = []
        if not company._potting_ncc():
            missing.append(_("NCC"))
        if not company.rex_code:
            missing.append(_("code REX (factures vers l'UE)"))
        if missing:
            return WARNING, _("À renseigner : %s.", ", ".join(missing))
        return OK, _("%(name)s — sigle %(short)s, NCC %(ncc)s.",
                     name=company._potting_trade_name(), short=company._potting_short_name(),
                     ncc=company._potting_ncc())

    def _check_company_bank(self):
        banks = self.env['res.partner.bank'].sudo().search(
            [('partner_id', '=', self._company().partner_id.id)])
        if not banks:
            return ERROR, _("Aucun compte bancaire sur la société : la facture export "
                            "n'aurait pas de domiciliation.")
        return OK, _("%s compte(s) : %s.", len(banks), ", ".join(banks.mapped('acc_number')))

    def _check_currency_rates(self):
        company = self._company()
        Rate = self.env['res.currency.rate'].sudo()
        today = fields.Date.context_today(self)
        missing, stale, fine = [], [], []
        for currency in self.env['res.currency'].search([('id', '!=', company.currency_id.id)]):
            rate = Rate.search([('currency_id', '=', currency.id), ('name', '<=', today),
                                ('company_id', 'in', (company.id, False))],
                               order='name desc', limit=1)
            if not rate:
                missing.append(currency.name)
            elif rate.name < today - timedelta(days=RATE_STALE_DAYS):
                stale.append('%s (%s)' % (currency.name, fields.Date.to_string(rate.name)))
            else:
                fine.append(currency.name)
        if missing:
            return ERROR, _("Sans taux : %s — une facture dans ces devises est refusée.",
                            ", ".join(missing))
        if not fine and not stale:
            return WARNING, _("Aucune devise étrangère active : activez les devises de "
                              "facturation (EUR, USD…) et leurs taux.")
        if stale:
            return WARNING, _("Taux de plus de %(days)s jours : %(list)s.",
                              days=RATE_STALE_DAYS, list=", ".join(stale))
        return OK, _("Taux à jour : %s.", ", ".join(fine) or _("aucune devise étrangère active"))

    def _check_export_campaign(self):
        campaign = self.env['potting.campaign'].get_current_campaign()
        if not campaign:
            return ERROR, _("Aucune campagne export en cours : CV, OT et lots en dépendent.")
        return OK, campaign.display_name

    def _check_ccc_taxes(self):
        count = self.env['potting.taxe.type'].search_count([])
        if not count:
            return ERROR, _("Aucun type de taxe : les formules FO1 seraient sans parafiscalités.")
        return OK, _("%s type(s) de taxe actifs.", count)

    def _check_lot_sequence(self):
        sequence = self.env['ir.sequence'].sudo().search([('code', '=', 'potting.lot.cocoa_beans')],
                                                         limit=1)
        if not sequence:
            return ERROR, _("Séquence « potting.lot.cocoa_beans » absente : les lots ne "
                            "peuvent pas être numérotés.")
        return OK, _("Prochain n° %s (préfixe des lots : %s).", sequence.number_next_actual,
                     self.env['res.config.settings'].get_lot_prefix_for_product('cocoa_beans'))

    def _check_sites(self):
        sites = self.env['cocoa.reception.site'].search([('company_id', '=', self._company().id)])
        if not sites:
            return ERROR, _("Aucun site : un lot d'usinage se rattache à son site.")
        # Sites livrés par le module fèves (données de départ d'ICP)
        seeded = sites.filtered(lambda s: s.get_external_id().get(s.id, '').startswith(
            'cocoa_bean_management.'))
        if seeded:
            return WARNING, _("Sites livrés à l'installation, à vérifier ou archiver : %s.",
                              ", ".join(seeded.mapped('name')))
        return OK, ", ".join(sites.mapped('name'))

    def _check_ports(self):
        Port = self.env['potting.port']
        loading = Port.search_count([('is_loading_port', '=', True)])
        discharge = Port.search_count([('is_discharge_port', '=', True)])
        if not loading or not discharge:
            return WARNING, _("Ports d'embarquement : %(l)s, de déchargement : %(d)s.",
                              l=loading, d=discharge)
        return OK, _("%(l)s port(s) d'embarquement, %(d)s de déchargement.",
                     l=loading, d=discharge)

    def _check_forwarders(self):
        count = self.env['potting.forwarding.agent'].search_count([])
        if not count:
            return WARNING, _("Aucun transitaire : l'OT et la formule en demandent un.")
        return OK, _("%s transitaire(s).", count)

    def _check_quality_standard(self):
        standard = self.env['cocoa.quality.standard'].sudo().search(
            [('is_default', '=', True)], limit=1)
        if not standard:
            return WARNING, _("Pas de norme des fèves ordinaires : la conformité des lots "
                              "d'usinage non certifiés n'est pas contrôlée.")
        mode = self.env['cocoa.bean.export.batch']._quality_control_mode()
        return OK, _("%(std)s (%(lines)s limites) — contrôle : %(mode)s.",
                     std=standard.name, lines=len(standard.line_ids),
                     mode=dict(self.env['res.config.settings']._fields[
                         'bean_export_quality_control'].selection)[mode])

    def _check_grade_grid(self):
        campaign = self.env['cocoa.campaign'].sudo()._get_for_date(
            fields.Date.context_today(self), self._company())
        if not campaign:
            return WARNING, _("Aucune campagne fèves aujourd'hui : le grade des lots "
                              "d'usinage n'est pas calculé.")
        graded = campaign.quality_criterion_ids.filtered(lambda c: c.max_g1 or c.max_g2)
        if not graded:
            return WARNING, _("%s : aucun seuil de grade renseigné.", campaign.name)
        return OK, _("%(c)s : %(n)s critère(s) de grade.", c=campaign.name, n=len(graded))

    def _check_documents(self):
        types = self.env['cocoa.bean.export.document.type'].search([])
        required = types.filtered(lambda t: t.requirement != 'optional')
        if not types:
            return WARNING, _("Aucun type de document d'export.")
        if not required:
            return WARNING, _("%s type(s), aucun exigé : rien ne bloque une expédition "
                              "incomplète.", len(types))
        return OK, _("%(n)s exigé(s) : %(list)s.", n=len(required),
                     list=", ".join(required.mapped('name')))

    def _check_managers(self):
        group = self.env.ref('potting_management.group_potting_manager')
        users = group.users.filtered(lambda u: u.active and not u.share
                                     and u != self.env.ref('base.user_root'))
        humans = users - self.env.ref('base.user_admin')
        if not humans:
            return WARNING, _("Seul l'administrateur est Manager Export : dérogations, "
                              "réclamations et vérifications EUDR lui reviendraient.")
        return OK, ", ".join(humans.mapped('name'))

    def _check_scope(self):
        company = self.env.company
        families = company._export_families()
        if FAMILY_BEANS not in families:
            return ERROR, _("%s n'exporte pas de fèves (Paramètres ▸ Filières "
                            "exportées).", company.name)
        group = self.env.ref(FAMILY_GROUPS[FAMILY_BEANS])
        holders = group.sudo().users.filtered(
            lambda u: u.active and not u.share and company in u.company_ids)
        if not holders:
            return ERROR, _("Aucun utilisateur de %s n'a la filière fèves : personne "
                            "ne verrait les documents de fèves.", company.name)
        if FAMILY_SEMI_FINISHED in families:
            return WARNING, _("Fèves et semi-finis (%s utilisateur(s) en filière fèves) : "
                              "vérifiez les filières de chaque utilisateur.", len(holders))
        return OK, _("Fèves uniquement (%s utilisateur(s) en filière fèves).", len(holders))


class CocoaBeanExportReadinessLine(models.TransientModel):
    _name = 'cocoa.bean.export.readiness.line'
    _description = "Contrôle de mise en service"
    _order = 'sequence'

    wizard_id = fields.Many2one('cocoa.bean.export.readiness', required=True,
                                ondelete='cascade')
    sequence = fields.Integer()
    key = fields.Char()
    section = fields.Char(string="Rubrique")
    name = fields.Char(string="Contrôle")
    status = fields.Selection([(ERROR, "Bloquant"), (WARNING, "À compléter"), (OK, "Conforme")],
                              string="Statut")
    detail = fields.Char(string="Détail")
    action_xmlid = fields.Char()

    def action_fix(self):
        self.ensure_one()
        return self.env['ir.actions.actions']._for_xml_id(self.action_xmlid)
