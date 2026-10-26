# -*- coding: utf-8 -*-
"""Tableaux de bord Export : filtre « Fèves / Semi-finis / Tout ».

Le socle ne connaît qu'une filière ; il délègue ici le choix des types de
produit comptés par ses trois tableaux de bord. Deux règles :

  * DROIT : ne sont jamais comptées que les filières des sociétés
    sélectionnées ET des groupes de l'utilisateur — le tableau de bord
    principal agrège en ``sudo``, la restriction doit donc passer ici ;
  * CHOIX : quand l'utilisateur voit les deux filières, il choisit Fèves,
    Semi-finis ou Tout (défaut) ; sinon aucun choix n'est proposé.
"""

from odoo import _, api, models

from .product_spec import FAMILIES, FAMILY_BEANS, FAMILY_SEMI_FINISHED

ALL_FAMILIES = 'all'


class PottingDashboardScopeFamily(models.AbstractModel):
    _inherit = 'potting.dashboard.scope'

    @api.model
    def resolve_product_family(self, product_family=None):
        Spec = self.env['potting.product.spec']
        visible = Spec._user_export_families()
        options = []
        if len(visible) > 1:
            options = [
                {'key': ALL_FAMILIES, 'label': _("Fèves et semi-finis")},
                {'key': FAMILY_BEANS, 'label': _("Fèves")},
                {'key': FAMILY_SEMI_FINISHED, 'label': _("Semi-finis")},
            ]
        if product_family not in visible:
            product_family = ALL_FAMILIES
        if product_family == ALL_FAMILIES:
            if set(FAMILIES) <= visible:
                # Tout est visible : aucune restriction à poser.
                return None, (ALL_FAMILIES if options else None), options
            selected = visible
        else:
            selected = {product_family}
        return (Spec._types_of_families(selected),
                product_family if options else None, options)
