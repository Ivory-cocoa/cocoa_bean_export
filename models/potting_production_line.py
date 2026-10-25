# -*- coding: utf-8 -*-
"""Ligne de production d'un lot de fèves = affectation d'un lot d'usinage.

Le socle calcule le tonnage d'une ligne en unités × poids nominal (cartons de
25 kg). Pour les fèves, le poids net est PESÉ au site : la ligne porte ce
poids (``bean_net_weight_kg``) et le tonnage en découle. Les garde-fous de
l'usine (plafond de production journalière, capacité comptée en unités) ne
s'appliquent pas à une affectation de fèves déjà pesées ; la capacité du lot
reste contrôlée en poids par ``potting.lot._check_production_lines_total``.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero, float_round

from .product_spec import PRODUCT_TYPE


class PottingProductionLineBeans(models.Model):
    _inherit = 'potting.production.line'

    bean_batch_id = fields.Many2one(
        'cocoa.bean.export.batch', string="Lot d'usinage",
        ondelete='restrict', index=True, check_company=True,
        help="Lot d'usinage du site dont proviennent ces fèves.")
    bean_net_weight_kg = fields.Float(
        string="Poids net pesé (kg)", digits=(16, 2),
        help="Poids net pesé au site pour cette affectation : il fait le "
             "tonnage de la ligne (fèves uniquement).")

    @api.depends('units_produced', 'packaging_unit_weight', 'bean_net_weight_kg')
    def _compute_tonnage(self):
        beans = self.filtered(lambda l: l.bean_batch_id or l.bean_net_weight_kg)
        for line in beans:
            line.tonnage = float_round((line.bean_net_weight_kg or 0.0) / 1000.0,
                                       precision_digits=6)
            line.tonnage_kg = float_round(line.bean_net_weight_kg or 0.0,
                                          precision_digits=2)
        super(PottingProductionLineBeans, self - beans)._compute_tonnage()

    def _is_bean_line(self):
        self.ensure_one()
        return self.product_type == PRODUCT_TYPE or bool(self.bean_batch_id)

    @api.constrains('units_produced')
    def _check_units_produced(self):
        beans = self.filtered(lambda l: l._is_bean_line())
        for line in beans:
            if line.units_produced <= 0:
                raise ValidationError(_("Le nombre d'unités produites doit être supérieur à 0."))
        super(PottingProductionLineBeans, self - beans)._check_units_produced()

    @api.constrains('lot_id', 'units_produced')
    def _check_lot_capacity(self):
        # Fèves : capacité contrôlée en poids pesé au niveau du lot
        # (_check_production_lines_total), pas en unités nominales.
        super(PottingProductionLineBeans, self.filtered(
            lambda l: not l._is_bean_line()))._check_lot_capacity()

    @api.constrains('bean_batch_id', 'bean_net_weight_kg', 'lot_id')
    def _check_bean_batch(self):
        for line in self:
            if not line._is_bean_line():
                continue
            if line.product_type != PRODUCT_TYPE:
                raise ValidationError(_(
                    "Un lot d'usinage ne s'affecte qu'à un lot de fèves "
                    "(lot %s).", line.lot_id.name))
            batch = line.bean_batch_id
            if not batch:
                raise ValidationError(_(
                    "Lot %s : une production de fèves provient d'un lot "
                    "d'usinage du site.", line.lot_id.name))
            if batch.state != 'confirmed':
                raise ValidationError(_(
                    "Le lot d'usinage %s doit être confirmé avant d'être "
                    "affecté.", batch.display_name))
            if float_is_zero(line.bean_net_weight_kg, precision_digits=2) \
                    or line.bean_net_weight_kg < 0:
                raise ValidationError(_(
                    "Lot %s : le poids net pesé de l'affectation doit être "
                    "positif.", line.lot_id.name))
            lot_cert = line.lot_id.certification_id
            if lot_cert != batch.certification_id:
                raise ValidationError(_(
                    "Certification incompatible : le lot %(lot)s est « %(lc)s » "
                    "et le lot d'usinage %(batch)s « %(bc)s ». Un lot export ne "
                    "mélange pas des fèves de certifications différentes.",
                    lot=line.lot_id.name,
                    lc=lot_cert.name or _("non certifié"),
                    batch=batch.display_name,
                    bc=batch.certification_id.name or _("non certifié")))
            # Le lot d'usinage ne peut pas être affecté au-delà de sa pesée
            batch._check_not_below_allocation()
            # Qualité : en mode « blocage », seule une dérogation motivée d'un
            # Manager (assistant de constitution) laisse passer.
            if batch._quality_control_mode() == 'block' \
                    and not self.env.context.get('bean_quality_override'):
                issues = batch._quality_issues_for_lot(line.lot_id)
                if issues:
                    raise ValidationError(_(
                        "Contrôle qualité (blocage) :\n%s\n\nUn Manager peut "
                        "déroger, avec un motif, depuis « Constituer le lot ».",
                        "\n".join("• " + issue for issue in issues)))
