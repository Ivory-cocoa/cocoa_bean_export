# -*- coding: utf-8 -*-
"""Amont suivi dans Odoo : l'usinage du site produit des lots d'usinage.

Le module fèves suit l'achat du cacao brousse (connaissements, pesées,
bordereaux BA, parcelles) et son USINAGE sur un site (cocoa.export.processing :
lots BA usinés, freinte). Chez ICP, le cacao usiné revient à l'usine (camions
RUT). Chez un exportateur de fèves, il part au port : la sortie de l'usinage
est faite de lots d'usinage (cocoa.bean.export.batch).

Rattacher un lot d'usinage à son usinage :
  * sa sortie nette entre dans la freinte de l'usinage (brousse usiné −
    cacao sorti), avec les alertes et retenues du module fèves ;
  * ses lots BA d'origine — donc leurs planteurs et parcelles — font foi
    pour l'EUDR, sans fichier GeoJSON à fournir.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CocoaBeanExportBatchProcessing(models.Model):
    _inherit = 'cocoa.bean.export.batch'

    processing_id = fields.Many2one(
        'cocoa.export.processing', string="Usinage", tracking=True, index=True,
        domain="[('site_id', '=', site_id), ('state', '=', 'processing')]",
        help="Usinage du module fèves dont ce lot est la sortie : lots BA "
             "d'origine (EUDR) et freinte.")

    @api.onchange('processing_id')
    def _onchange_processing_id(self):
        processing = self.processing_id
        if processing:
            self.site_id = processing.site_id
            if not self.site_lot_ref:
                self.site_lot_ref = processing.site_lot_ref

    @api.constrains('processing_id', 'site_id', 'certification_id', 'state')
    def _check_processing(self):
        for batch in self.filtered('processing_id'):
            processing = batch.processing_id
            if processing.site_id != batch.site_id:
                raise ValidationError(_(
                    "Le lot d'usinage %(batch)s est pesé à %(site)s, l'usinage "
                    "%(proc)s se fait à %(proc_site)s.",
                    batch=batch.name, site=batch.site_id.name, proc=processing.name,
                    proc_site=processing.site_id.name))
            expected = processing.certification_id
            actual = batch.certification_id.sudo().cocoa_certification_id
            if expected != actual:
                raise ValidationError(_(
                    "Certification : l'usinage %(proc)s porte « %(exp)s », le lot "
                    "d'usinage %(batch)s « %(act)s ».",
                    proc=processing.name,
                    exp=expected.name or _("ordinaire"), batch=batch.name,
                    act=batch.certification_id.name or _("conventionnel")))

    def action_confirm(self):
        for batch in self.filtered(lambda b: b.state == 'draft' and b.processing_id):
            if batch.processing_id.state != 'processing':
                raise UserError(_(
                    "L'usinage %s n'est pas en cours : un lot d'usinage ne s'y "
                    "rattache plus.", batch.processing_id.display_name))
        return super().action_confirm()

    def write(self, vals):
        # Une sortie d'usinage clôturé ne change plus : la freinte et les
        # retenues ont été calculées dessus.
        sensitive = {'gross_weight_kg', 'tare_weight_kg', 'processing_id', 'state'}
        if sensitive & set(vals) and not self.env.context.get('bean_batch_correction'):
            closed = self.filtered(lambda b: b.processing_id.state == 'closed')
            if closed:
                raise UserError(_(
                    "L'usinage de %s est clôturé : sa sortie est figée.",
                    ", ".join(closed.mapped('name'))))
        return super().write(vals)

    def _eudr_source_lots(self):
        return super()._eudr_source_lots() | self.sudo().processing_id.line_ids.lot_id


class CocoaExportProcessingBeanExport(models.Model):
    _inherit = 'cocoa.export.processing'

    export_batch_ids = fields.One2many(
        'cocoa.bean.export.batch', 'processing_id', string="Lots d'usinage (export)")
    export_batch_count = fields.Integer(compute='_compute_export_batch_count')

    @api.depends('export_batch_ids')
    def _compute_export_batch_count(self):
        for processing in self:
            processing.export_batch_count = len(processing.export_batch_ids)

    def _confirmed_export_batches(self):
        return self.sudo().export_batch_ids.filtered(lambda b: b.state == 'confirmed')

    def _output_kg(self):
        return super()._output_kg() + sum(
            self._confirmed_export_batches().mapped('net_weight_kg'))

    def _has_output(self):
        return super()._has_output() or bool(self._confirmed_export_batches())

    @api.depends('reception_ids.state', 'reception_ids.net_payable_kg',
                 'reception_ids.declared_net_kg', 'input_t', 'state',
                 'reception_ids.site_net_gap_kg', 'normal_freinte_pct', 'source_cost',
                 'export_batch_ids.state', 'export_batch_ids.net_weight_kg')
    def _compute_received(self):
        return super()._compute_received()

    def action_close(self):
        drafts = self.export_batch_ids.filtered(lambda b: b.state == 'draft')
        if drafts:
            raise UserError(_(
                "Lots d'usinage encore en brouillon : %s. Confirmez-les ou "
                "annulez-les avant de clôturer l'usinage.", ", ".join(drafts.mapped('name'))))
        return super().action_close()

    def action_new_export_batch(self):
        self.ensure_one()
        if self.state != 'processing':
            raise UserError(_("Seul un usinage en cours reçoit des lots d'usinage."))
        cert = self.env['potting.certification'].search(
            [('cocoa_certification_id', '=', self.certification_id.id)], limit=1) \
            if self.certification_id else self.env['potting.certification']
        return {
            'type': 'ir.actions.act_window',
            'name': _("Lot d'usinage — %s", self.display_name),
            'res_model': 'cocoa.bean.export.batch',
            'view_mode': 'form',
            'context': {
                'default_processing_id': self.id,
                'default_site_id': self.site_id.id,
                'default_site_lot_ref': self.site_lot_ref,
                'default_certification_id': cert.id,
            },
        }

    def action_view_export_batches(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Lots d'usinage — %s", self.display_name),
            'res_model': 'cocoa.bean.export.batch',
            'view_mode': 'tree,form',
            'domain': [('processing_id', '=', self.id)],
            'context': {'default_processing_id': self.id, 'default_site_id': self.site_id.id},
        }
