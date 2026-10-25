# -*- coding: utf-8 -*-
"""Formule FO1 de fèves : tonnage converti = tonnage (coefficient 1).

Le coefficient de conversion ramène un semi-fini à son équivalent fèves
(1,25 par défaut). Pour des fèves il vaut 1 par définition : sinon toutes les
taxes CCC (assiette = prix de référence × tonnage converti) seraient gonflées
de 25 %.
"""

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .product_spec import PRODUCT_TYPE


class PottingFormuleBeans(models.Model):
    _inherit = 'potting.formule'

    @api.model
    def _get_bean_coefficients(self):
        coefficients = super()._get_bean_coefficients()
        coefficients[PRODUCT_TYPE] = 1.0
        return coefficients

    @api.onchange('product_type')
    def _onchange_product_type_bean_coefficient(self):
        if self.product_type == PRODUCT_TYPE:
            self.coefficient_conversion = 1.0

    # Le socle calcule l'équivalent fèves (tonnage × 1000 × coefficient) à la
    # création comme à toute écriture du tonnage ou du coefficient : forcer le
    # coefficient à 1 suffit.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('product_type') == PRODUCT_TYPE:
                vals['coefficient_conversion'] = 1.0
        return super().create(vals_list)

    def write(self, vals):
        # Le type de produit arrive souvent APRÈS la création (synchronisation
        # depuis l'OT) : la formule gardait alors le coefficient 1,25 par
        # défaut et la contrainte la refusait au lieu de la corriger.
        if vals.get('product_type') == PRODUCT_TYPE and 'coefficient_conversion' not in vals:
            vals = dict(vals, coefficient_conversion=1.0)
        return super().write(vals)

    @api.constrains('product_type', 'coefficient_conversion')
    def _check_bean_coefficient(self):
        for formule in self:
            if formule.product_type == PRODUCT_TYPE and float_compare(
                    formule.coefficient_conversion, 1.0, precision_digits=3):
                raise ValidationError(_(
                    "Formule %s : pour des fèves, le coefficient de conversion "
                    "vaut 1 (le tonnage converti est le tonnage de fèves).",
                    formule.display_name))
