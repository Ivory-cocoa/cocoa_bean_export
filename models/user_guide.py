# -*- coding: utf-8 -*-
"""Guide utilisateur « Export des fèves » (moteur : cocoa_bean_management).

Un chapitre par étape du circuit, filtré par profil ; gabarits
views/guide/beans_guide_<fr|en>.xml (mêmes clés dans les deux langues).
"""

from odoo import api, models

P = 'potting_management.group_potting_'


class IcpUserGuideBeans(models.AbstractModel):
    _inherit = 'icp.user.guide'

    @api.model
    def _guide_registry(self):
        registry = super()._guide_registry()
        access = [P + g for g in ('commercial', 'shipping', 'accountant', 'production',
                                  'container_manager', 'bl_manager', 'payment_manager',
                                  'pdg', 'cv_manager', 'manager')]
        registry['beans'] = {
            'module': 'cocoa_bean_export',
            'eyebrow': {'fr': 'Guide utilisateur', 'en': 'User guide'},
            'title': {'fr': 'Export des fèves de cacao',
                      'en': 'Cocoa bean exports'},
            'subtitle': {
                'fr': "Lots d'usinage, constitution des lots export au poids pesé, qualité, "
                      "documents d'expédition, EUDR et réclamations à l'arrivée.",
                'en': "Processing batches, export lots built on weighed net weight, quality, "
                      "shipping documents, EUDR and arrival claims."},
            'filter_by_profile': True,
            'access_groups': access,
            'filename': {'fr': 'Guide_Export_Feves.pdf', 'en': 'Cocoa_Bean_Export_Guide.pdf'},
            'chapters': self._bean_export_chapters(),
        }
        return registry

    @api.model
    def _bean_export_chapters(self):
        def ch(key, groups, fr, en):
            return {'key': key, 'groups': [P + g for g in groups],
                    'title': {'fr': fr, 'en': en}}
        return [
            ch('start', [], "Le circuit des fèves en un coup d'œil",
               'The bean export process at a glance'),
            ch('batches', ['shipping', 'production', 'container_manager'],
               "Lots d'usinage : saisir et importer les pesées du site",
               'Processing batches: entering and importing site weighings'),
            ch('constitution', ['shipping', 'production', 'container_manager'],
               "Constituer les lots export", 'Building export lots'),
            ch('quality', ['shipping', 'manager'], "Qualité : normes, grades, dérogations",
               'Quality: standards, grades, overrides'),
            ch('documents', ['shipping', 'bl_manager', 'accountant'],
               "Documents d'expédition du BL", 'Shipping documents of the B/L'),
            ch('eudr', ['shipping', 'bl_manager', 'manager'], "EUDR des fèves",
               'EUDR for beans'),
            ch('claims', ['shipping', 'bl_manager', 'accountant', 'manager'],
               "Réclamations à l'arrivée", 'Arrival claims'),
            ch('settings', ['manager'], "Réglages et mise en service",
               'Settings and go-live'),
            ch('faq', [], "Messages d'erreur et questions fréquentes",
               'Error messages and FAQ'),
        ]
