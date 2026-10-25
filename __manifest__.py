# -*- coding: utf-8 -*-
{
    'name': "Exportation des fèves de cacao",
    'version': '17.0.1.0.0',
    'category': 'Inventory/Logistics',
    'summary': "Export de fèves de cacao brutes sur le socle Gestion des Exportations",
    'description': """
Exportation des fèves de cacao brutes (SH 1801)
===============================================

Ajoute le type de produit « Fèves de cacao » au module Gestion des
Exportations (potting_management) : contrats, CV, formules FO1, OT, lots,
conteneurs, BL, D6, factures, soutien/reversement et tableaux de bord sont
ceux du socle — une seule réglementation CCC, une seule base de code.

Propre aux fèves :

- Lots d'usinage du site (bulletin de pesée de sortie : n° de lot du site,
  sacs, poids brut / tare / net pesés, qualité, certification) ;
- Constitution des lots export à partir des lots d'usinage : le tonnage du
  lot est le poids NET PESÉ, jamais un nombre de sacs × poids nominal ;
- Conditionnement réglable : sacs de jute (poids nominal et tare) ou vrac ;
- Code SH 1801 00 00 00, coefficient de conversion fèves = 1 (assiette des
  taxes CCC), facteur Mass Balance = 1 ;
- Mode « fèves uniquement » : les semi-finis disparaissent des listes de
  choix, des tableaux de bord et des menus de production.
""",
    'author': 'ICP',
    'website': 'https://www.icp.com',
    'license': 'LGPL-3',
    'depends': [
        'potting_management',
        'cocoa_bean_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/bean_export_security.xml',
        'data/ir_sequence_data.xml',
        'data/product_data.xml',
        'data/ir_config_parameter_data.xml',
        'wizards/bean_lot_constitution_wizard_views.xml',
        'views/bean_export_batch_views.xml',
        'views/potting_lot_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/bean_quality_config_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
