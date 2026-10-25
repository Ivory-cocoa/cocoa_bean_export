# -*- coding: utf-8 -*-
"""Amont suivi dans Odoo : usinage du module fèves → lots d'usinage export.

Verrouille : la sortie nette des lots d'usinage fait la freinte de
l'usinage ; l'usinage se clôture sans camion RUT ; ses lots BA font foi pour
l'EUDR ; site et certification doivent concorder ; la sortie d'un usinage
clôturé est figée.
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.cocoa_bean_management.tests.test_export_processing import ExportCase


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestBeanProcessingBridge(ExportCase):

    def _export_batch(self, processing, gross=29000.0, tare=300.0, bags=450,
                      ticket='DS-BRIDGE', confirm=True, **vals):
        batch = self.env['cocoa.bean.export.batch'].create(dict({
            'processing_id': processing.id,
            'site_id': processing.site_id.id,
            'site_lot_ref': processing.site_lot_ref,
            'weighing_ticket': ticket,
            'bag_count': bags,
            'gross_weight_kg': gross,
            'tare_weight_kg': tare,
        }, **vals))
        if confirm:
            batch.action_confirm()
        return batch

    def test_100_export_batches_are_the_processing_output(self):
        ba = self._ba_lot(30.0)
        processing = self._batch([ba], start=True)
        batch = self._export_batch(processing)
        self.assertEqual(batch.net_weight_kg, 28700.0)
        processing.invalidate_recordset()
        self.assertAlmostEqual(processing.received_t, 28.7, places=3)
        self.assertAlmostEqual(processing.freinte_t, 1.3, places=3)
        self.assertEqual(processing.freinte_state, 'running')
        processing.action_close()
        self.assertEqual(processing.state, 'closed')
        self.assertIn(processing.freinte_state, ('normal', 'excess'))
        with self.assertRaises(UserError):
            batch.gross_weight_kg = 29500.0

    def test_101_ba_lots_are_the_eudr_source(self):
        ba = self._ba_lot(30.0)
        processing = self._batch([ba], start=True)
        batch = self._export_batch(processing, ticket='DS-EUDR')
        self.assertEqual(batch._eudr_source_lots(), ba)
        self.assertEqual(batch.eudr_state, ba.eudr_state)
        self.assertFalse(batch._eudr_supplied_features())

    def test_102_site_must_match(self):
        ba = self._ba_lot(30.0)
        processing = self._batch([ba], start=True)
        other = self.env['cocoa.reception.site'].create({
            'name': 'Autre site', 'site_type': 'external'})
        with self.assertRaises(ValidationError):
            self._export_batch(processing, ticket='DS-SITE', site_id=other.id)

    def test_103_draft_batch_blocks_closing(self):
        ba = self._ba_lot(30.0)
        processing = self._batch([ba], start=True)
        self._export_batch(processing, ticket='DS-OK')
        self._export_batch(processing, ticket='DS-DRAFT', confirm=False)
        with self.assertRaises(UserError):
            processing.action_close()

    def test_104_closing_without_any_output_is_refused(self):
        ba = self._ba_lot(30.0)
        processing = self._batch([ba], start=True)
        with self.assertRaises(UserError):
            processing.action_close()

    def test_105_new_batch_action_prefills(self):
        ba = self._ba_lot(30.0)
        processing = self._batch([ba], start=True)
        context = processing.action_new_export_batch()['context']
        self.assertEqual(context['default_processing_id'], processing.id)
        self.assertEqual(context['default_site_id'], self.sitapa.id)
