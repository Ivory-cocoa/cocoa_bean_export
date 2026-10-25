# -*- coding: utf-8 -*-
"""Lot export de fèves : constitué de lots d'usinage du site."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .product_spec import PRODUCT_TYPE


class PottingLotBeans(models.Model):
    _inherit = 'potting.lot'

    bean_batch_ids = fields.Many2many(
        'cocoa.bean.export.batch', string="Lots d'usinage",
        compute='_compute_bean_batches',
        help="Lots d'usinage du site dont est constitué ce lot export.")
    bean_batch_count = fields.Integer(compute='_compute_bean_batches')
    is_bean_lot = fields.Boolean(compute='_compute_is_bean_lot')

    @api.depends('production_line_ids.bean_batch_id')
    def _compute_bean_batches(self):
        for lot in self:
            batches = lot.production_line_ids.mapped('bean_batch_id')
            lot.bean_batch_ids = batches
            lot.bean_batch_count = len(batches)

    @api.depends('product_type')
    def _compute_is_bean_lot(self):
        for lot in self:
            lot.is_bean_lot = lot.product_type == PRODUCT_TYPE

    @api.constrains('certification_id')
    def _check_bean_certification(self):
        """Changer la certification d'un lot déjà constitué la ferait
        diverger de celle des fèves qui le composent."""
        for lot in self.filtered('is_bean_lot'):
            mismatched = lot.bean_batch_ids.filtered(
                lambda b: b.certification_id != lot.certification_id)
            if mismatched:
                raise ValidationError(_(
                    "Le lot %(lot)s contient des fèves « %(cert)s » (%(batches)s) : "
                    "sa certification ne peut pas être changée.",
                    lot=lot.name,
                    cert=mismatched[0].certification_id.name or _("non certifiées"),
                    batches=", ".join(mismatched.mapped('name'))))

    def action_open_bean_constitution(self):
        self.ensure_one()
        if not self.is_bean_lot:
            raise UserError(_("Seul un lot de fèves se constitue à partir de "
                              "lots d'usinage."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Constituer le lot %s", self.name),
            'res_model': 'cocoa.bean.lot.constitution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lot_id': self.id},
        }

    def action_view_bean_batches(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Lots d'usinage"),
            'res_model': 'cocoa.bean.export.batch',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.bean_batch_ids.ids)],
        }
