# -*- coding: utf-8 -*-
"""Filières d'export par société et par utilisateur.

Une société exporte des fèves, des semi-finis (masse, beurre, cake, poudre),
ou les deux. Ce choix lui est propre : dans une même base, ICP reste aux
semi-finis, SOCAGC aux fèves, et une troisième société peut faire les deux.

Un utilisateur ne voit que les filières de ses groupes « Filière fèves » et
« Filière semi-finis » (règles d'accès, listes de choix, tableaux de bord).
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .product_spec import (FAMILIES, FAMILY_BEANS, FAMILY_GROUPS,
                           FAMILY_SEMI_FINISHED, PRODUCT_TYPE)

FAMILY_LABELS = {
    FAMILY_BEANS: "Fèves de cacao",
    FAMILY_SEMI_FINISHED: "Semi-finis",
}


def family_domain(family, field='product_type'):
    """Domaine des enregistrements d'une filière sur un champ « type »."""
    if family == FAMILY_BEANS:
        return [(field, '=', PRODUCT_TYPE)]
    return [(field, '!=', False), (field, '!=', PRODUCT_TYPE)]


class ResCompany(models.Model):
    _inherit = 'res.company'

    export_beans = fields.Boolean(
        string="Exporte des fèves de cacao",
        help="La société exporte des fèves brutes (SH 1801).")
    export_semi_finished = fields.Boolean(
        string="Exporte des semi-finis", default=True,
        help="La société exporte de la masse, du beurre, du cake ou de la "
             "poudre de cacao.")

    def _export_families(self):
        """Filières exportées par au moins une de ces sociétés."""
        families = set()
        for company in self:
            if company.export_beans:
                families.add(FAMILY_BEANS)
            if company.export_semi_finished:
                families.add(FAMILY_SEMI_FINISHED)
        return families

    @api.constrains('export_beans', 'export_semi_finished')
    def _check_export_families(self):
        for company in self:
            if not (company.export_beans or company.export_semi_finished):
                raise ValidationError(_(
                    "%s doit exporter au moins une filière (fèves ou "
                    "semi-finis).", company.name))
            for family in FAMILIES:
                if family in company._export_families():
                    continue
                open_docs = company._open_export_documents(family)
                if open_docs:
                    raise ValidationError(_(
                        "%(company)s a encore des documents « %(family)s » en "
                        "cours : %(docs)s. Terminez-les ou annulez-les avant "
                        "de retirer cette filière.",
                        company=company.name, family=FAMILY_LABELS[family],
                        docs=", ".join(open_docs)))

    def _open_export_documents(self, family):
        """« 3 OT, 1 contrat » : documents en cours d'une filière (sudo)."""
        self.ensure_one()
        found = []
        for model, open_domain, label in (
                ('potting.transit.order',
                 [('state', 'not in', ('done', 'cancelled'))], _("OT")),
                ('potting.customer.order',
                 [('state', 'in', ('draft', 'in_progress'))], _("contrat(s)"))):
            count = self.env[model].sudo().with_context(active_test=False).search_count(
                [('company_id', '=', self.id)] + open_domain + family_domain(family))
            if count:
                found.append("%s %s" % (count, label))
        return found


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _export_families(self):
        """Filières accordées à l'utilisateur (le superutilisateur : toutes)."""
        self.ensure_one()
        if self._is_superuser():
            return set(FAMILIES)
        return {family for family, xmlid in FAMILY_GROUPS.items()
                if self.has_group(xmlid)}

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._bean_export_grant_default_families()
        return users

    def _bean_export_grant_default_families(self):
        """Un nouvel utilisateur interne sans filière reçoit celles de ses
        sociétés — le comportement d'avant les filières. Un administrateur
        les restreint ensuite s'il le faut."""
        groups = {family: self.env.ref(xmlid, raise_if_not_found=False)
                  for family, xmlid in FAMILY_GROUPS.items()}
        if not all(groups.values()):
            return
        family_group_ids = {group.id for group in groups.values()}
        for user in self.filtered(lambda u: not u.share):
            if family_group_ids & set(user.groups_id.ids):
                continue
            families = user.sudo().company_ids._export_families()
            if families:
                user.sudo().write({'groups_id': [
                    (4, groups[family].id) for family in sorted(families)]})
