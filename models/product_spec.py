# -*- coding: utf-8 -*-
"""Type « Fèves de cacao » dans le registre des types de produit du socle.

Le conditionnement est réglable (Paramètres ▸ Export fèves) : sacs de jute
(poids nominal et tare par sac) ou vrac. En vrac, l'unité de conditionnement
est le kilogramme : le nombre d'« unités » d'une ligne est son poids net pesé
et la tare est portée par le conteneur (liner), pas par l'unité.
"""

from odoo import api, models

PRODUCT_TYPE = 'cocoa_beans'

PARAM_PACKAGING = 'cocoa_bean_export.packaging'          # 'bags' | 'bulk'
PARAM_BAG_WEIGHT = 'cocoa_bean_export.bag_weight_kg'
# Ancien réglage global « exporter aussi des semi-finis » (jusqu'à 17.0.1.x) :
# remplacé par les filières de chaque société, lu une seule fois par la
# migration 17.0.2.0.0.
LEGACY_PARAM_WITH_SEMI_FINISHED = 'cocoa_bean_export.with_semi_finished'

# Filières d'export : une société exporte des fèves, des semi-finis, ou les
# deux (res.company.export_beans / export_semi_finished) ; un utilisateur n'en
# voit que celles de ses groupes « Filière fèves » / « Filière semi-finis ».
FAMILY_BEANS = 'beans'
FAMILY_SEMI_FINISHED = 'semi_finished'
FAMILIES = (FAMILY_BEANS, FAMILY_SEMI_FINISHED)
FAMILY_GROUPS = {
    FAMILY_BEANS: 'cocoa_bean_export.group_bean_export_beans',
    FAMILY_SEMI_FINISHED: 'cocoa_bean_export.group_bean_export_semi_finished',
}


def family_of(product_type):
    """Filière d'un type de produit (semi-finis : tout ce qui n'est pas fève)."""
    return FAMILY_BEANS if product_type == PRODUCT_TYPE else FAMILY_SEMI_FINISHED

DEFAULT_BAG_WEIGHT_KG = 65.0
# Tare d'un sac de jute (kg) : paramètre du socle potting_management.tare_<type>
DEFAULT_BAG_TARE_KG = 1.0


def _to_float(value, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class PottingProductSpecBeans(models.AbstractModel):
    _inherit = 'potting.product.spec'

    @api.model
    def _bean_export_settings(self):
        ICP = self.env['ir.config_parameter'].sudo()
        packaging = ICP.get_param(PARAM_PACKAGING) or 'bags'
        return {
            'packaging': packaging if packaging in ('bags', 'bulk') else 'bags',
            'bag_weight_kg': _to_float(ICP.get_param(PARAM_BAG_WEIGHT),
                                       DEFAULT_BAG_WEIGHT_KG),
        }

    @api.model
    def _get_product_specs(self):
        specs = super()._get_product_specs()
        settings = self._bean_export_settings()
        bulk = settings['packaging'] == 'bulk'
        bag_kg = settings['bag_weight_kg']
        specs[PRODUCT_TYPE] = {
            'sequence': 5,
            'label': "Fèves de cacao",
            'short_label': "Fèves",
            'report_label': "FÈVES",
            'payment_label': "FÈVES",
            'nature_label': "FÈVES DE CACAO",
            'hs_code': '1801.00.00',
            'nomenclature': '1801 00 00 00',
            'unit_weight': 0.001 if bulk else bag_kg / 1000.0,
            'unit_name': 'kg' if bulk else 'sac',
            'unit_name_plural': 'kg' if bulk else 'sacs',
            'packaging_description': ('vrac (poids net pesé)' if bulk else
                                      'sac de jute de %s kg' % ('%g' % bag_kg)),
            'packaging_label': 'VRAC' if bulk else 'SACS',
            'packaging_type_label': 'VRAC' if bulk else 'SACS DE JUTE',
            'emballage_type': 'vrac' if bulk else 'sacs',
            # Pas de délai de cristallisation : l'empotage des fèves n'est
            # pas mesuré par le suivi des délais d'exécution de l'usine.
            'potting_delay_days': None,
            'default_ot_tonnage': 100.0,
            'max_tonnage': 25.0,
            'tare_kg': 0.0 if bulk else DEFAULT_BAG_TARE_KG,
            'lot_prefix': 'F',
            'ot_code': 'FE',
            'icon': 'fa-leaf',
            'color': '#5D4037',
            'emoji': '🌰',
            'import_aliases': ('feves', 'feve', 'feves de cacao',
                               'cacao en feves', 'cacao feves', 'cocoa beans',
                               'beans', 'raw cocoa beans'),
            'bulk': bulk,
        }
        families = self._active_export_families()
        for code, spec in specs.items():
            if family_of(code) not in families:
                spec['active'] = False
        return specs

    @api.model
    def _active_export_families(self):
        """Filières proposées ici et maintenant.

        Celles des sociétés sélectionnées (``env.companies``), restreintes à
        celles de l'utilisateur — sauf en ``sudo`` ou pour le superutilisateur
        (crons, calculs serveur), où seules les sociétés comptent. Les écrans
        qui agrègent en ``sudo`` (tableaux de bord) filtrent eux-mêmes par
        utilisateur.
        """
        families = self.env.companies._export_families()
        if not self.env.su:
            families &= self.env.user._export_families()
        return families

    @api.model
    def _user_export_families(self):
        """Filières visibles par l'utilisateur courant, même en ``sudo`` :
        celles de ses sociétés sélectionnées ET de ses groupes."""
        return (self.env.companies._export_families()
                & self.env.user._export_families())

    @api.model
    def _types_of_families(self, families):
        """Codes des types de produit des filières données (inactifs compris)."""
        return [code for code in self.get_product_types(include_inactive=True)
                if family_of(code) in families]
