# -*- coding: utf-8 -*-
"""Lot d'usinage : fèves usinées au site, prêtes à partir au port.

Chez un exportateur de fèves, le cacao est usiné (nettoyé, ensaché) sur un
site, pesé à la sortie et empoté sans repasser par une usine. Le bulletin de
pesée de sortie du site fait foi : n° de lot du site, nombre de sacs, poids
brut, tare et net. Ce lot d'usinage est la source du tonnage exporté — les
lots export (potting.lot) en sont constitués par des lignes de production
qui portent le poids net PESÉ (jamais sacs × poids nominal).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round

GRADES = [
    ('GF', "Grade I — Good Fermented"),
    ('F', "Grade II — Fair Fermented"),
    ('SS', "Sous-grade (Sub-Standard)"),
    ('LIMIT', "Limite"),
]


class CocoaBeanExportBatch(models.Model):
    _name = 'cocoa.bean.export.batch'
    _description = "Lot d'usinage (fèves export)"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string="Référence", required=True, copy=False, readonly=True,
        default=lambda self: _("Nouveau"), index=True)
    state = fields.Selection([
        ('draft', "Brouillon"),
        ('confirmed', "Confirmé"),
        ('cancelled', "Annulé"),
    ], string="État", default='draft', required=True, tracking=True,
        copy=False, index=True)
    company_id = fields.Many2one(
        'res.company', string="Société", required=True, index=True,
        default=lambda self: self.env.company)

    # --- Origine : bulletin de pesée de sortie du site ----------------------
    site_id = fields.Many2one(
        'cocoa.reception.site', string="Site d'usinage", required=True,
        tracking=True, check_company=True,
        domain="[('company_id', '=', company_id)]")
    site_lot_ref = fields.Char(
        string="N° de lot du site", required=True, tracking=True, index=True,
        help="Numéro du lot d'usinage imprimé sur le bulletin de pesée du "
             "site (« Lots : 5011 »).")
    weighing_ticket = fields.Char(
        string="N° bulletin de pesée", tracking=True, index=True, copy=False,
        help="Numéro du bulletin de pesée de sortie du site.")
    date = fields.Date(
        string="Date de pesée", required=True, tracking=True,
        default=fields.Date.context_today)
    campaign_id = fields.Many2one(
        'potting.campaign', string="Campagne", tracking=True,
        default=lambda self: self.env['potting.campaign'].get_current_campaign())

    # --- Poids et sacs -----------------------------------------------------
    bag_count = fields.Integer(
        string="Nombre de sacs", tracking=True,
        help="Sacs pesés. Vide en vrac.")
    gross_weight_kg = fields.Float(
        string="Poids brut (kg)", digits=(16, 2), tracking=True)
    tare_weight_kg = fields.Float(
        string="Tare (kg)", digits=(16, 2), tracking=True,
        help="Tare des sacs (et palettes) du bulletin de pesée.")
    net_weight_kg = fields.Float(
        string="Poids net (kg)", digits=(16, 2), store=True,
        compute='_compute_net_weight',
        help="Brut − tare : poids net pesé, qui fait foi pour l'export.")
    net_per_bag_kg = fields.Float(
        string="Net moyen par sac (kg)", digits=(16, 3),
        compute='_compute_net_weight', store=True)
    is_bulk = fields.Boolean(
        string="Vrac", compute='_compute_is_bulk',
        help="Conditionnement réglé en vrac : l'affectation se fait en kg.")

    # --- Qualité et certification -------------------------------------------
    grade = fields.Selection(GRADES, string="Grade", tracking=True)
    moisture_pct = fields.Float(string="Humidité (%)", digits=(5, 2))
    bean_count = fields.Integer(
        string="Grainage (fèves / 100 g)",
        help="Nombre de fèves pour 100 g.")
    mouldy_pct = fields.Float(string="Moisies (%)", digits=(5, 2))
    slaty_pct = fields.Float(string="Ardoisées (%)", digits=(5, 2))
    insect_damaged_pct = fields.Float(string="Mitées / insectes (%)", digits=(5, 2))
    quality_certificate_ref = fields.Char(
        string="N° certificat qualité", tracking=True,
        help="Référence du certificat de qualité (contrôle CCC) du lot.")
    certification_id = fields.Many2one(
        'potting.certification', string="Certification", tracking=True,
        help="Vide : fèves conventionnelles (non certifiées).")
    note = fields.Text(string="Notes")

    # --- Affectation aux lots export -----------------------------------------
    production_line_ids = fields.One2many(
        'potting.production.line', 'bean_batch_id',
        string="Affectations aux lots export", readonly=True)
    lot_ids = fields.Many2many(
        'potting.lot', string="Lots export", compute='_compute_allocation')
    allocated_bags = fields.Integer(
        string="Sacs affectés", compute='_compute_allocation', store=True)
    allocated_net_kg = fields.Float(
        string="Net affecté (kg)", digits=(16, 2),
        compute='_compute_allocation', store=True)
    remaining_bags = fields.Integer(
        string="Sacs disponibles", compute='_compute_allocation', store=True)
    remaining_net_kg = fields.Float(
        string="Net disponible (kg)", digits=(16, 2),
        compute='_compute_allocation', store=True)
    allocation_status = fields.Selection([
        ('free', "Disponible"),
        ('partial', "Partiellement affecté"),
        ('full', "Entièrement affecté"),
    ], string="Affectation", compute='_compute_allocation', store=True, index=True)

    _sql_constraints = [
        ('bag_count_positive', 'CHECK(bag_count IS NULL OR bag_count >= 0)',
         "Le nombre de sacs ne peut pas être négatif."),
    ]

    # ------------------------------------------------------------------
    # Calculs
    # ------------------------------------------------------------------
    @api.depends('gross_weight_kg', 'tare_weight_kg', 'bag_count')
    def _compute_net_weight(self):
        for batch in self:
            net = float_round((batch.gross_weight_kg or 0.0)
                              - (batch.tare_weight_kg or 0.0), precision_digits=2)
            batch.net_weight_kg = net
            batch.net_per_bag_kg = (float_round(net / batch.bag_count, precision_digits=3)
                                    if batch.bag_count else 0.0)

    def _compute_is_bulk(self):
        bulk = bool(self.env['potting.product.spec'].get_value('cocoa_beans', 'bulk'))
        for batch in self:
            batch.is_bulk = bulk

    @api.depends('production_line_ids.units_produced',
                 'production_line_ids.bean_net_weight_kg',
                 'production_line_ids.packaging_unit_name',
                 'production_line_ids.lot_id', 'net_weight_kg', 'bag_count')
    def _compute_allocation(self):
        for batch in self:
            lines = batch.production_line_ids
            batch.lot_ids = lines.mapped('lot_id')
            batch.allocated_net_kg = float_round(
                sum(lines.mapped('bean_net_weight_kg')), precision_digits=2)
            batch.remaining_net_kg = float_round(
                (batch.net_weight_kg or 0.0) - batch.allocated_net_kg,
                precision_digits=2)
            # Une ligne en vrac compte des kg, pas des sacs : on lit l'unité
            # figée sur la ligne, pas le réglage du moment.
            batch.allocated_bags = sum(
                lines.filtered(lambda l: l.packaging_unit_name != 'kg')
                .mapped('units_produced'))
            batch.remaining_bags = max((batch.bag_count or 0) - batch.allocated_bags, 0)
            if not lines:
                batch.allocation_status = 'free'
            elif float_compare(batch.remaining_net_kg, 0.0, precision_digits=2) <= 0:
                batch.allocation_status = 'full'
            else:
                batch.allocation_status = 'partial'

    @api.depends('name', 'site_lot_ref', 'site_id')
    def _compute_display_name(self):
        for batch in self:
            parts = [batch.name or '']
            if batch.site_lot_ref:
                parts.append(_("lot site %s", batch.site_lot_ref))
            if batch.site_id:
                parts.append(batch.site_id.name)
            batch.display_name = " — ".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Contraintes
    # ------------------------------------------------------------------
    @api.constrains('gross_weight_kg', 'tare_weight_kg')
    def _check_weights(self):
        for batch in self:
            if batch.gross_weight_kg < 0 or batch.tare_weight_kg < 0:
                raise ValidationError(_("Les poids ne peuvent pas être négatifs."))
            if batch.gross_weight_kg and float_compare(
                    batch.tare_weight_kg, batch.gross_weight_kg, precision_digits=2) >= 0:
                raise ValidationError(_(
                    "Lot d'usinage %s : la tare doit être inférieure au poids brut.",
                    batch.display_name))

    @api.constrains('site_id', 'site_lot_ref', 'weighing_ticket', 'company_id')
    def _check_unique_ticket(self):
        """Un même bulletin de pesée ne peut être saisi deux fois."""
        for batch in self.filtered('weighing_ticket'):
            duplicate = self.search([
                ('id', '!=', batch.id),
                ('company_id', '=', batch.company_id.id),
                ('site_id', '=', batch.site_id.id),
                ('weighing_ticket', '=ilike', batch.weighing_ticket.strip()),
                ('state', '!=', 'cancelled'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Le bulletin de pesée %(ticket)s du site %(site)s est déjà "
                    "saisi (%(other)s).",
                    ticket=batch.weighing_ticket, site=batch.site_id.name,
                    other=duplicate.name))

    @api.constrains('net_weight_kg', 'bag_count', 'state')
    def _check_not_below_allocation(self):
        """Corriger une pesée ne peut pas rendre l'affectation impossible."""
        for batch in self:
            if float_compare(batch.allocated_net_kg, batch.net_weight_kg,
                             precision_digits=2) > 0:
                raise ValidationError(_(
                    "Lot d'usinage %(batch)s : %(alloc).2f kg sont déjà affectés "
                    "à des lots export, plus que le poids net (%(net).2f kg).",
                    batch=batch.display_name, alloc=batch.allocated_net_kg,
                    net=batch.net_weight_kg))
            if batch.bag_count and batch.allocated_bags > batch.bag_count:
                raise ValidationError(_(
                    "Lot d'usinage %(batch)s : %(alloc)s sacs déjà affectés, plus "
                    "que les %(bags)s sacs pesés.",
                    batch=batch.display_name, alloc=batch.allocated_bags,
                    bags=batch.bag_count or 0))

    # ------------------------------------------------------------------
    # CRUD et actions
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _("Nouveau")) == _("Nouveau"):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'cocoa.bean.export.batch') or _("Nouveau")
        return super().create(vals_list)

    def write(self, vals):
        weighing = {'gross_weight_kg', 'tare_weight_kg', 'bag_count', 'site_id',
                    'certification_id'}
        if weighing & set(vals) and not self.env.context.get('bean_batch_correction'):
            locked = self.filtered(lambda b: b.state == 'confirmed' and b.production_line_ids)
            if locked:
                raise UserError(_(
                    "Le lot d'usinage %s est déjà affecté à des lots export : "
                    "sa pesée, son site et sa certification ne se modifient "
                    "plus. Retirez d'abord ses affectations.",
                    ", ".join(locked.mapped('name'))))
        return super().write(vals)

    def unlink(self):
        if self.mapped('production_line_ids'):
            raise UserError(_(
                "Un lot d'usinage affecté à des lots export ne peut pas être "
                "supprimé. Retirez d'abord ses affectations."))
        if self.filtered(lambda b: b.state == 'confirmed'):
            raise UserError(_("Annulez le lot d'usinage avant de le supprimer."))
        return super().unlink()

    def action_confirm(self):
        for batch in self:
            if batch.state != 'draft':
                continue
            missing = []
            if float_is_zero(batch.net_weight_kg, precision_digits=2) or batch.net_weight_kg < 0:
                missing.append(_("poids brut et tare (net positif)"))
            if not batch.is_bulk and not batch.bag_count:
                missing.append(_("nombre de sacs"))
            if missing:
                raise UserError(_(
                    "Lot d'usinage %(batch)s : renseignez %(missing)s avant de "
                    "le confirmer.", batch=batch.display_name,
                    missing=", ".join(missing)))
            batch.state = 'confirmed'
        return True

    def action_cancel(self):
        if self.mapped('production_line_ids'):
            raise UserError(_(
                "Un lot d'usinage affecté à des lots export ne peut pas être "
                "annulé. Retirez d'abord ses affectations."))
        self.write({'state': 'cancelled'})
        return True

    def action_draft(self):
        if self.mapped('production_line_ids'):
            raise UserError(_(
                "Un lot d'usinage affecté à des lots export ne repasse pas en "
                "brouillon. Retirez d'abord ses affectations."))
        self.write({'state': 'draft'})
        return True

    def action_view_lots(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Lots export"),
            'res_model': 'potting.lot',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.lot_ids.ids)],
        }
