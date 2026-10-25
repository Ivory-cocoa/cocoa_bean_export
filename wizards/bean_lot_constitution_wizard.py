# -*- coding: utf-8 -*-
"""Constituer un lot export de fèves à partir de lots d'usinage du site.

Chaque ligne affecte des sacs (ou des kg en vrac) d'un lot d'usinage au lot
export : une ligne de production est créée avec le poids net PESÉ
correspondant — au prorata des sacs, et le reste exact du lot d'usinage
quand on prend ses derniers sacs (aucune dérive d'arrondi).

« Lot complet » ramène le tonnage cible du lot à son poids net réel : le lot
passe alors « prêt pour empotage » comme un lot d'usine plein.
"""

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, float_round


class CocoaBeanLotConstitutionWizard(models.TransientModel):
    _name = 'cocoa.bean.lot.constitution.wizard'
    _description = "Constitution d'un lot export de fèves"

    lot_id = fields.Many2one('potting.lot', string="Lot export", required=True,
                             readonly=True)
    company_id = fields.Many2one(related='lot_id.company_id')
    certification_id = fields.Many2one(related='lot_id.certification_id')
    is_bulk = fields.Boolean(compute='_compute_lot_info')
    target_tonnage = fields.Float(related='lot_id.target_tonnage', string="Cible (T)")
    current_tonnage = fields.Float(related='lot_id.current_tonnage', string="Déjà constitué (T)")
    line_ids = fields.One2many('cocoa.bean.lot.constitution.wizard.line', 'wizard_id',
                               string="Lots d'usinage à affecter")
    added_net_kg = fields.Float(string="Net ajouté (kg)", digits=(16, 2),
                                compute='_compute_totals')
    resulting_tonnage = fields.Float(string="Tonnage du lot après (T)", digits=(16, 3),
                                     compute='_compute_totals')
    complete_lot = fields.Boolean(
        string="Lot complet",
        help="Le lot est plein : son tonnage cible devient son poids net "
             "réel et il passe « prêt pour empotage ».")
    date = fields.Date(string="Date d'affectation", required=True,
                       default=fields.Date.context_today)
    quality_mode = fields.Char(compute='_compute_quality_issues')
    quality_issues = fields.Text(
        string="Constats qualité", compute='_compute_quality_issues')
    quality_override = fields.Boolean(
        string="Déroger au contrôle qualité",
        help="Réservé aux Managers, en mode « blocage » : les lots d'usinage "
             "sont affectés malgré les constats, le motif est tracé sur le lot.")
    quality_override_reason = fields.Text(string="Motif de la dérogation")

    @api.depends('lot_id')
    def _compute_lot_info(self):
        for wizard in self:
            wizard.is_bulk = wizard.lot_id.packaging_unit_name == 'kg'

    @api.depends('line_ids.batch_id', 'lot_id')
    def _compute_quality_issues(self):
        mode = self.env['cocoa.bean.export.batch']._quality_control_mode()
        for wizard in self:
            wizard.quality_mode = mode
            issues = wizard._collect_quality_issues(wizard.line_ids)
            wizard.quality_issues = "\n".join("• " + i for i in issues)

    @api.depends('line_ids.net_weight_kg', 'current_tonnage')
    def _compute_totals(self):
        for wizard in self:
            wizard.added_net_kg = sum(wizard.line_ids.mapped('net_weight_kg'))
            wizard.resulting_tonnage = (wizard.current_tonnage or 0.0) \
                + wizard.added_net_kg / 1000.0

    def action_confirm(self):
        self.ensure_one()
        lot = self.lot_id
        if not lot.is_bean_lot:
            raise UserError(_("Seul un lot de fèves se constitue à partir de lots d'usinage."))
        if lot.state not in ('draft', 'in_production', 'ready'):
            raise UserError(_(
                "Le lot %s est déjà empoté ou clôturé : sa composition ne "
                "change plus.", lot.name))
        lines = self.line_ids.filtered(lambda l: l.quantity > 0)
        if not lines and not self.complete_lot:
            raise UserError(_("Indiquez au moins un lot d'usinage et une quantité."))
        if len(lines.mapped('batch_id')) != len(lines):
            raise UserError(_("Un même lot d'usinage figure sur plusieurs lignes."))
        for line in lines:
            line._check_quantity()
        issues = self._collect_quality_issues(lines)
        override = False
        if issues and self.quality_mode == 'block':
            if not self.quality_override:
                raise UserError(_(
                    "Contrôle qualité (blocage) :\n%s\n\nUn Manager peut "
                    "cocher « Déroger au contrôle qualité » et donner un motif.",
                    "\n".join("• " + i for i in issues)))
            if not self.env.user.has_group('potting_management.group_potting_manager'):
                raise UserError(_("Seul un Manager peut déroger au contrôle qualité."))
            if not (self.quality_override_reason or '').strip():
                raise UserError(_("Indiquez le motif de la dérogation."))
            override = True

        new_total = float_round(
            (lot.current_tonnage or 0.0) + sum(lines.mapped('net_weight_kg')) / 1000.0,
            precision_digits=6)
        if float_compare(new_total, lot.target_tonnage, precision_digits=4) > 0:
            if not self.complete_lot:
                raise UserError(_(
                    "Le lot %(lot)s atteindrait %(total).3f T pour une cible de "
                    "%(target).3f T. Cochez « Lot complet » pour le clôturer à son "
                    "poids réel, ou réduisez les quantités.",
                    lot=lot.name, total=new_total, target=lot.target_tonnage))
            if new_total > 50:
                raise UserError(_("Un lot ne peut pas dépasser 50 T (%.3f T).") % new_total)
            # Relever la cible avant d'ajouter les lignes (contrôle total ≤ cible)
            lot.target_tonnage = new_total

        # La création des lignes démarre le lot et l'OT (socle)
        ProductionLine = self.env['potting.production.line'].with_context(
            bean_quality_override=override)
        for line in lines:
            ProductionLine.create(line._prepare_production_line_vals())

        if self.complete_lot:
            lot.invalidate_recordset(['current_tonnage'])
            if float_is_zero(lot.current_tonnage, precision_digits=6):
                raise UserError(_("Le lot %s est vide : il ne peut pas être "
                                  "déclaré complet.", lot.name))
            if float_compare(lot.current_tonnage, lot.target_tonnage, precision_digits=6) < 0:
                lot.target_tonnage = lot.current_tonnage
            lot._auto_transition_on_fill()
        lot.message_post(body=_(
            "Lot constitué de %(count)s lot(s) d'usinage (+%(net).2f kg net pesé)%(complete)s.",
            count=len(lines), net=sum(lines.mapped('net_weight_kg')),
            complete=_(" — lot complet") if self.complete_lot else ''))
        if issues:
            Batch = self.env['cocoa.bean.export.batch']
            title = (_("Dérogation qualité (Manager) — motif : %s",
                       self.quality_override_reason.strip())
                     if override else _("Avertissement qualité"))
            lot.message_post(body=Markup("<p><strong>%s</strong></p>%s") % (
                title, Batch._quality_issues_html(issues)))
        return {'type': 'ir.actions.act_window_close'}

    def _collect_quality_issues(self, lines):
        if self.env['cocoa.bean.export.batch']._quality_control_mode() == 'off':
            return []
        issues = []
        for batch in lines.mapped('batch_id'):
            issues += batch._quality_issues_for_lot(self.lot_id)
        return issues


class CocoaBeanLotConstitutionWizardLine(models.TransientModel):
    _name = 'cocoa.bean.lot.constitution.wizard.line'
    _description = "Lot d'usinage à affecter"

    wizard_id = fields.Many2one('cocoa.bean.lot.constitution.wizard', required=True,
                                ondelete='cascade')
    batch_id = fields.Many2one(
        'cocoa.bean.export.batch', string="Lot d'usinage", required=True,
        domain="[('state', '=', 'confirmed'), ('allocation_status', '!=', 'full'), "
               "('company_id', '=', parent.company_id), "
               "('certification_id', '=', parent.certification_id)]")
    remaining_bags = fields.Integer(related='batch_id.remaining_bags')
    remaining_net_kg = fields.Float(related='batch_id.remaining_net_kg')
    quantity = fields.Integer(
        string="Sacs (kg en vrac)",
        help="Nombre de sacs pris dans le lot d'usinage ; en vrac, kg net.")
    net_weight_kg = fields.Float(string="Net pesé (kg)", digits=(16, 2),
                                 compute='_compute_net_weight')

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        if self.batch_id and not self.quantity:
            self.quantity = (int(self.batch_id.remaining_net_kg)
                             if self.wizard_id.is_bulk else self.batch_id.remaining_bags)

    @api.depends('batch_id', 'quantity', 'wizard_id.is_bulk')
    def _compute_net_weight(self):
        for line in self:
            batch = line.batch_id
            if not batch or line.quantity <= 0:
                line.net_weight_kg = 0.0
            elif line.wizard_id.is_bulk:
                line.net_weight_kg = min(float(line.quantity), batch.remaining_net_kg)
            elif line.quantity >= batch.remaining_bags:
                # Derniers sacs : tout le reste pesé, sans arrondi résiduel
                line.net_weight_kg = batch.remaining_net_kg
            else:
                line.net_weight_kg = float_round(
                    batch.net_per_bag_kg * line.quantity, precision_digits=2)

    def _check_quantity(self):
        self.ensure_one()
        batch = self.batch_id
        if self.wizard_id.is_bulk:
            if float_compare(self.quantity, batch.remaining_net_kg + 0.5, precision_digits=2) > 0:
                raise UserError(_(
                    "Lot d'usinage %(batch)s : %(qty)s kg demandés, %(left).2f kg disponibles.",
                    batch=batch.display_name, qty=self.quantity, left=batch.remaining_net_kg))
        elif self.quantity > batch.remaining_bags:
            raise UserError(_(
                "Lot d'usinage %(batch)s : %(qty)s sacs demandés, %(left)s disponibles.",
                batch=batch.display_name, qty=self.quantity, left=batch.remaining_bags))

    def _prepare_production_line_vals(self):
        self.ensure_one()
        batch = self.batch_id
        return {
            'lot_id': self.wizard_id.lot_id.id,
            'bean_batch_id': batch.id,
            'bean_net_weight_kg': self.net_weight_kg,
            'units_produced': self.quantity,
            # La ligne ne peut pas être datée après aujourd'hui ; la pesée du
            # site la précède normalement.
            'date': min(batch.date, self.wizard_id.date),
            'batch_number': batch.site_lot_ref,
            'quality_ok': True,
            'note': batch.weighing_ticket and _("Bulletin de pesée %s", batch.weighing_ticket),
        }
