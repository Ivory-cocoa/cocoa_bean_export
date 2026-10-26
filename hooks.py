# -*- coding: utf-8 -*-
"""Mise en place des filières d'export (installation et migration 17.0.2.0.0).

Chaque société reçoit les filières de son activité actuelle, déduites de ses
documents — jamais d'une hypothèse qui en masquerait :

  * installation dans une base qui exporte déjà des semi-finis (ICP) : les
    sociétés gardent les semi-finis seuls ; les fèves s'activent ensuite, à
    la main, pour la société qui en exporte ;
  * installation dans une base neuve (exportateur de fèves) : fèves seules ;
  * migration depuis 17.0.1.x (réglage global « exporter aussi des
    semi-finis ») : fèves partout, semi-finis selon l'ancien réglage.

Chaque utilisateur interne reçoit les filières de ses sociétés : personne ne
perd l'accès à un document le jour de la mise à jour ; les droits se
restreignent ensuite utilisateur par utilisateur.
"""

import logging

from .models.export_family import FAMILY_LABELS
from .models.product_spec import (FAMILY_BEANS, FAMILY_GROUPS, FAMILY_SEMI_FINISHED,
                                  LEGACY_PARAM_WITH_SEMI_FINISHED, PRODUCT_TYPE)

_logger = logging.getLogger(__name__)

# Documents qui révèlent l'activité d'une société
_ACTIVITY_MODELS = ('potting.customer.order', 'potting.transit.order',
                    'potting.confirmation.vente', 'potting.formule')


def _company_activity(env, company):
    """(a des documents de fèves, a des documents de semi-finis)."""
    beans = semi = False
    for model in _ACTIVITY_MODELS:
        Model = env[model].sudo().with_context(active_test=False)
        base = [('company_id', '=', company.id)]
        beans = beans or bool(Model.search_count(
            base + [('product_type', '=', PRODUCT_TYPE)], limit=1))
        semi = semi or bool(Model.search_count(
            base + [('product_type', 'not in', (PRODUCT_TYPE, 'all', False))], limit=1))
    return beans, semi


def setup_export_families(env, legacy_with_semi_finished=None):
    """Filières des sociétés puis des utilisateurs.

    :param legacy_with_semi_finished: valeur de l'ancien réglage global
        (migration), ou None pour une installation.
    """
    companies = env['res.company'].sudo().with_context(active_test=False).search([])
    activity = {company: _company_activity(env, company) for company in companies}
    base_has_semi = any(semi for _beans, semi in activity.values())
    for company, (has_beans, has_semi) in activity.items():
        if legacy_with_semi_finished is None:
            semi = has_semi or (base_has_semi and not has_beans)
            beans = has_beans or not semi
        else:
            beans = True
            semi = bool(legacy_with_semi_finished) or has_semi
        company.write({'export_beans': beans, 'export_semi_finished': semi})
        _logger.info("Export : %s exporte %s.", company.name, " + ".join(
            label for flag, label in ((beans, "fèves"), (semi, "semi-finis")) if flag))

    groups = {family: env.ref(xmlid) for family, xmlid in FAMILY_GROUPS.items()}
    # L'ancien groupe technique était impliqué par tous les utilisateurs
    # internes : la filière semi-finis se donne désormais utilisateur par
    # utilisateur.
    internal = env.ref('base.group_user').sudo()
    semi_group = groups[FAMILY_SEMI_FINISHED].sudo()
    if semi_group in internal.implied_ids:
        internal.write({'implied_ids': [(3, semi_group.id)]})

    users = env['res.users'].sudo().with_context(active_test=False).search(
        [('share', '=', False)])
    for family in (FAMILY_BEANS, FAMILY_SEMI_FINISHED):
        members = users.filtered(lambda u: family in u.company_ids._export_families())
        if members:
            groups[family].sudo().write({'users': [(4, user.id) for user in members]})
        _logger.info("Export : filière %s accordée à %s utilisateur(s).",
                     FAMILY_LABELS[family], len(members))
    env['res.config.settings']._bean_export_sync_menus()


def post_init_hook(env):
    setup_export_families(env)


def migrate_from_global_setting(env):
    ICP = env['ir.config_parameter'].sudo()
    raw = ICP.get_param(LEGACY_PARAM_WITH_SEMI_FINISHED)
    legacy = str(raw or '').strip().lower() not in ('', '0', 'false', 'none')
    setup_export_families(env, legacy_with_semi_finished=legacy)
    ICP.search([('key', '=', LEGACY_PARAM_WITH_SEMI_FINISHED)]).unlink()
