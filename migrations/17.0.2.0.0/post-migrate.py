# -*- coding: utf-8 -*-
"""17.0.2.0.0 : réglage global « exporter aussi des semi-finis » → filières
par société et par utilisateur (voir hooks.setup_export_families)."""

from odoo import SUPERUSER_ID, api

from odoo.addons.cocoa_bean_export.hooks import migrate_from_global_setting


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrate_from_global_setting(env)
