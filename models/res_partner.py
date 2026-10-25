# -*- coding: utf-8 -*-
"""Numérotation des lots de fèves propre à un client non principal."""

from odoo import fields, models


class ResPartnerBeans(models.Model):
    _inherit = 'res.partner'

    potting_lot_next_seq_cocoa_beans = fields.Integer(
        string="Séquence lot Fèves", default=1,
        help="Prochain numéro de séquence pour les lots Fèves de ce client.")
    potting_lot_prefix_cocoa_beans = fields.Char(
        string="Initiale lot Fèves", size=5,
        help="Préfixe/initiale pour les lots Fèves de ce client (ex: F, FE...)")
