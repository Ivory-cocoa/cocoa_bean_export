# -*- coding: utf-8 -*-
"""Valeur « Fèves de cacao » sur toutes les sélections « type de produit ».

Le socle déclare la liste des semi-finis dans chaque champ (contrat, OT, lot,
CV, formule, produits, assistants d'import et de rapport). Chacun reçoit ici
``cocoa_beans`` ; le test ``test_every_product_type_selection_has_beans``
échoue si un nouveau champ du socle est oublié.

Mode « fèves uniquement » (réglage, actif par défaut) : les semi-finis sont
retirés des listes de choix (``fields_get``) et refusés à l'enregistrement
sur les documents métier. Les champs gardent leur sélection complète côté
serveur : un libellé reste lisible et rien ne casse si le mode est coupé.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .product_spec import PRODUCT_TYPE

BEANS = [(PRODUCT_TYPE, "Fèves de cacao")]


def _block_uninstall(records):
    """Désinstaller le module laisserait des documents d'un type inconnu."""
    raise UserError(_(
        "Impossible de désinstaller l'export des fèves : %(count)s "
        "enregistrement(s) « %(model)s » sont de type Fèves de cacao.",
        count=len(records), model=records._description))


ONDELETE = {PRODUCT_TYPE: _block_uninstall}


class BeanProductTypeMixin(models.AbstractModel):
    """Masque les types inactifs dans les listes de choix du client web."""
    _name = 'cocoa.bean.export.product.type.mixin'
    _description = "Types de produit proposés (export fèves)"

    # Champs « type de produit » du modèle à filtrer dans les listes de choix
    _bean_product_type_fields = ('product_type',)
    # Champs refusant un type inactif à l'enregistrement (documents métier)
    _bean_product_type_guarded = ()

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        Spec = self.env['potting.product.spec']
        known = set(Spec.get_product_types(include_inactive=True))
        active = set(Spec.get_product_types())
        for name in self._bean_product_type_fields:
            desc = res.get(name)
            if desc and desc.get('selection'):
                desc['selection'] = [
                    (value, label) for value, label in desc['selection']
                    if value not in known or value in active]
        return res

    def _check_bean_product_type_active(self):
        Spec = self.env['potting.product.spec']
        known = set(Spec.get_product_types(include_inactive=True))
        active = set(Spec.get_product_types())
        for record in self:
            for name in self._bean_product_type_guarded:
                value = record[name]
                if value and value in known and value not in active:
                    raise ValidationError(_(
                        "« %(type)s » n'est pas exporté par cette société "
                        "(réglage « Fèves uniquement »). Choisissez « Fèves "
                        "de cacao ».",
                        type=dict(record._fields[name].selection).get(value, value)))


# ----------------------------------------------------------------------------
# Documents métier : valeur ajoutée, filtrée et contrôlée
# ----------------------------------------------------------------------------

class PottingCustomerOrder(models.Model):
    _name = 'potting.customer.order'
    _inherit = ['potting.customer.order', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_guarded = ('product_type',)

    product_type = fields.Selection(selection_add=BEANS, ondelete=ONDELETE)

    @api.constrains('product_type')
    def _check_bean_export_product_type(self):
        self._check_bean_product_type_active()


class PottingTransitOrder(models.Model):
    _name = 'potting.transit.order'
    _inherit = ['potting.transit.order', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_guarded = ('product_type',)

    product_type = fields.Selection(selection_add=BEANS, ondelete=ONDELETE)

    @api.constrains('product_type')
    def _check_bean_export_product_type(self):
        self._check_bean_product_type_active()


class PottingLot(models.Model):
    _name = 'potting.lot'
    _inherit = ['potting.lot', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_guarded = ('product_type',)

    product_type = fields.Selection(selection_add=BEANS, ondelete=ONDELETE)

    @api.constrains('product_type')
    def _check_bean_export_product_type(self):
        self._check_bean_product_type_active()


class PottingFormule(models.Model):
    _name = 'potting.formule'
    _inherit = ['potting.formule', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_guarded = ('product_type',)

    product_type = fields.Selection(selection_add=BEANS, ondelete=ONDELETE)

    @api.constrains('product_type')
    def _check_bean_export_product_type(self):
        self._check_bean_product_type_active()


class PottingConfirmationVente(models.Model):
    _name = 'potting.confirmation.vente'
    _inherit = ['potting.confirmation.vente', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_guarded = ('product_type',)

    # La CV garde « Tous produits » (« all ») après les types.
    product_type = fields.Selection(
        selection_add=[(PRODUCT_TYPE, "Fèves de cacao"), ('all',)],
        ondelete=ONDELETE)

    @api.constrains('product_type')
    def _check_bean_export_product_type(self):
        self._check_bean_product_type_active()


class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = ['product.product', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_fields = ('potting_product_type',)

    potting_product_type = fields.Selection(
        selection_add=BEANS, ondelete={PRODUCT_TYPE: 'set null'})


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_fields = ('potting_product_type',)

    potting_product_type = fields.Selection(
        selection_add=BEANS, ondelete={PRODUCT_TYPE: 'set null'})


# ----------------------------------------------------------------------------
# Assistants (imports, rapports, génération) : valeur ajoutée et filtrée.
# Enregistrements temporaires : supprimés avec la valeur à la désinstallation
# (« set null » est refusé par Odoo sur un champ obligatoire).
# ----------------------------------------------------------------------------

WIZARD_ONDELETE = {PRODUCT_TYPE: 'cascade'}


class CreateOtWizard(models.TransientModel):
    _name = 'potting.create.ot.wizard'
    _inherit = ['potting.create.ot.wizard', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class GenerateOtFromOrderWizard(models.TransientModel):
    _name = 'potting.generate.ot.from.order.wizard'
    _inherit = ['potting.generate.ot.from.order.wizard', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class LotReferenceNormalizeWizard(models.TransientModel):
    _name = 'potting.lot.reference.normalize.wizard'
    _inherit = ['potting.lot.reference.normalize.wizard', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class DailyReportWizard(models.TransientModel):
    _name = 'potting.daily.report.wizard'
    _inherit = ['potting.daily.report.wizard', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_fields = ('filter_product_type',)

    filter_product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class ImportFormuleWizardLine(models.TransientModel):
    _name = 'potting.import.formule.wizard.line'
    _inherit = ['potting.import.formule.wizard.line', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class ImportCvWizardLine(models.TransientModel):
    _name = 'potting.import.cv.wizard.line'
    _inherit = ['potting.import.cv.wizard.line', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class ImportContractsWizardLine(models.TransientModel):
    _name = 'potting.import.contracts.wizard.line'
    _inherit = ['potting.import.contracts.wizard.line', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class ImportOtWizard(models.TransientModel):
    _name = 'potting.import.ot.wizard'
    _inherit = ['potting.import.ot.wizard', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class PdgExportReportWizard(models.TransientModel):
    _name = 'potting.pdg.export.report.wizard'
    _inherit = ['potting.pdg.export.report.wizard', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class ProductionAlignmentWizard(models.TransientModel):
    _name = 'potting.production.alignment.wizard'
    _inherit = ['potting.production.alignment.wizard', 'cocoa.bean.export.product.type.mixin']

    product_type = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)


class DusCalculationWizard(models.TransientModel):
    _name = 'potting.dus.calculation.wizard'
    _inherit = ['potting.dus.calculation.wizard', 'cocoa.bean.export.product.type.mixin']
    _bean_product_type_fields = ('product_subtype',)

    product_subtype = fields.Selection(selection_add=BEANS, ondelete=WIZARD_ONDELETE)
