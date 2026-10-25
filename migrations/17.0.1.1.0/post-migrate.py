# -*- coding: utf-8 -*-
"""17.0.1.1.0 — documents d'export : chaque BL de fèves existant reçoit les
lignes des types de documents (statut « manquant »). Rejouable sans effet."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    notes = env['potting.delivery.note'].search([
        ('product_type', '=', 'cocoa_beans'), ('state', '!=', 'cancelled')])
    notes.action_bean_documents_sync()
