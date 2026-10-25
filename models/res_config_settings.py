# -*- coding: utf-8 -*-
"""Paramètres ▸ Export fèves."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .product_spec import (DEFAULT_BAG_WEIGHT_KG, PARAM_BAG_WEIGHT,
                           PARAM_PACKAGING, PARAM_WITH_SEMI_FINISHED)


class ResConfigSettingsBeans(models.TransientModel):
    _inherit = 'res.config.settings'

    bean_export_with_semi_finished = fields.Boolean(
        string="Exporter aussi des semi-finis",
        config_parameter=PARAM_WITH_SEMI_FINISHED,
        help="Décoché (défaut) : seules les fèves sont proposées ; masse, "
             "beurre, cake et poudre disparaissent des listes de choix et "
             "des tableaux de bord.")
    bean_export_packaging = fields.Selection([
        ('bags', "Sacs de jute"),
        ('bulk', "Vrac (liner)"),
    ], string="Conditionnement des fèves", default='bags',
        config_parameter=PARAM_PACKAGING,
        help="Sacs : les lots se comptent en sacs (poids nominal ci-dessous) "
             "et en poids net pesé. Vrac : en kg net pesé. S'applique aux "
             "lots créés ensuite ; les lots existants gardent leur "
             "conditionnement.")
    bean_export_bag_weight_kg = fields.Float(
        string="Poids nominal d'un sac (kg)", digits=(6, 2),
        default=DEFAULT_BAG_WEIGHT_KG, config_parameter=PARAM_BAG_WEIGHT,
        help="Sert à estimer le nombre de sacs d'un lot à constituer. Le "
             "tonnage réel est toujours le poids net pesé.")
    bean_export_bag_tare_kg = fields.Float(
        string="Tare d'un sac (kg)", digits=(6, 3), default=1.0,
        config_parameter='potting_management.tare_cocoa_beans',
        help="Poids d'un sac de jute vide : poids brut = net + sacs × tare.")
    bean_export_max_lot_tonnage = fields.Float(
        string="Tonnage maximal d'un lot (T)", digits=(6, 3), default=25.0,
        config_parameter='potting_management.max_tonnage_cocoa_beans',
        help="Découpage d'un OT de fèves en lots (un lot = un conteneur, en "
             "général).")
    bean_export_quality_control = fields.Selection([
        ('off', "Désactivé"),
        ('warn', "Avertissement (tracé sur le lot)"),
        ('block', "Blocage (dérogation motivée d'un Manager)"),
    ], string="Contrôle qualité des lots d'usinage", default='warn',
        config_parameter='cocoa_bean_export.quality_control',
        help="À la constitution d'un lot export : lot d'usinage non conforme "
             "à la norme de sa certification, ou de grade inférieur à celui "
             "de la CV de l'OT.")
    bean_export_weight_franchise_pct = fields.Float(
        string="Franchise de poids à l'arrivée (%)", digits=(5, 3), default=0.5,
        config_parameter='cocoa_bean_export.weight_franchise_pct',
        help="Perte de poids admise entre le net embarqué et le net débarqué "
             "avant réclamation (valeur proposée sur chaque réclamation).")
    bean_export_lot_prefix = fields.Char(
        string="Préfixe des lots de fèves", default='F',
        config_parameter='potting_management.lot_prefix_cocoa_beans')

    @api.constrains('bean_export_bag_weight_kg', 'bean_export_bag_tare_kg',
                    'bean_export_max_lot_tonnage', 'bean_export_weight_franchise_pct')
    def _check_bean_export_settings(self):
        for settings in self:
            if settings.bean_export_bag_weight_kg <= 0:
                raise ValidationError(_("Le poids nominal d'un sac doit être positif."))
            if settings.bean_export_bag_tare_kg < 0:
                raise ValidationError(_("La tare d'un sac ne peut pas être négative."))
            if not 0 <= settings.bean_export_weight_franchise_pct <= 10:
                raise ValidationError(_("La franchise de poids doit être comprise entre 0 et 10 %."))
            if not 0 < settings.bean_export_max_lot_tonnage <= 50:
                raise ValidationError(_(
                    "Le tonnage maximal d'un lot doit être compris entre 0 et 50 T."))

    @api.model
    def get_packaging_tare_for_product(self, product_type):
        # En vrac, l'unité est le kg net : une tare « par unité » n'a pas de
        # sens (la tare du liner est celle du conteneur).
        if product_type == 'cocoa_beans' and self.env['potting.product.spec'] \
                .get_value(product_type, 'bulk'):
            return 0.0
        return super().get_packaging_tare_for_product(product_type)

    # Menus propres à une usine de transformation (production de semi-finis,
    # écran usine, atelier, vente locale des sous-produits) : sans objet chez
    # un exportateur de fèves seules.
    _BEAN_EXPORT_FACTORY_MENUS = (
        'potting_management.menu_potting_quick_production',
        'potting_management.menu_potting_production_order',
        'potting_management.menu_potting_factory_screen',
        'potting_management.menu_production_daily_report',
        'potting_management.menu_production_report_compare',
        'potting_management.menu_potting_workshop',
        'potting_management.menu_potting_local',
    )

    @api.model
    def _bean_export_sync_menus(self):
        """Aligne l'interface sur « fèves uniquement » : menus d'usine et
        filtres de recherche des semi-finis (groupe technique accordé à tous
        les utilisateurs internes, ou retiré — comme un implied_group)."""
        show = not self.env['potting.product.spec']._is_beans_only()
        for xmlid in self._BEAN_EXPORT_FACTORY_MENUS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu and menu.active != show:
                menu.sudo().active = show
        semi_finished = self.env.ref(
            'cocoa_bean_export.group_bean_export_semi_finished', raise_if_not_found=False)
        internal = self.env.ref('base.group_user').sudo()
        if semi_finished:
            semi_finished = semi_finished.sudo()
            if show and semi_finished not in internal.implied_ids:
                internal.write({'implied_ids': [(4, semi_finished.id)]})
            elif not show and semi_finished in internal.implied_ids:
                internal.write({'implied_ids': [(3, semi_finished.id)]})
                # Retirer l'implication ne retire pas les membres (Odoo)
                semi_finished.write({'users': [(3, user.id) for user in semi_finished.users]})
        return True

    def set_values(self):
        super().set_values()
        self._bean_export_sync_menus()
