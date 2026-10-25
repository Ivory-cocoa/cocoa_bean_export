# -*- coding: utf-8 -*-
"""Export de fèves : type de produit, lots d'usinage, constitution des lots.

Ce que ces tests verrouillent :
  * chaque sélection « type de produit » du socle connaît les fèves (un champ
    oublié ferait planter un assistant ou disparaître des lignes d'un état) ;
  * le mode « fèves uniquement » retire les semi-finis des listes et les
    refuse à l'enregistrement ;
  * le tonnage d'un lot export de fèves est le poids NET PESÉ des lots
    d'usinage qui le composent — jamais sacs × poids nominal — et la
    dernière affectation d'un lot d'usinage en prend le reste exact ;
  * un lot d'usinage ne s'affecte ni au-delà de sa pesée, ni à un lot d'une
    autre certification, ni avant d'être confirmé ;
  * la formule FO1 de fèves a un coefficient de conversion de 1.
"""

import base64
from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged

from odoo.addons.potting_management.tests.common import get_xof, make_campaign

# Sélections qui ne décrivent PAS un produit exporté (usine, marché local,
# déblocage de fèves pour la transformation) : volontairement sans fèves.
EXCLUDED_SELECTIONS = {
    ('potting.production.order', 'product_type'),
    ('potting.quick.production.wizard', 'filter_product_type'),
    ('potting.quick.local.production.wizard', 'filter_product_type'),
    ('potting.local.product', 'product_type'),
    ('cocoa.bean.consumption', 'product_type'),
    ('cocoa.bean.consumption.batch', 'product_type'),
    # Le déblocage de CV a sa propre valeur « feves » (fèves débloquées
    # pour la transformation), distincte du produit exporté.
    ('potting.cv.deblocage', 'product_type'),
}


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class BeanExportCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        cls.campaign = make_campaign(
            cls.env, 'Campagne fèves', date.today() - timedelta(days=30),
            date.today() + timedelta(days=335))
        cls.customer = cls.env['res.partner'].create({
            'name': 'Acheteur fèves', 'ref': 'ACHF', 'is_company': True})
        cls.consignee = cls.env['res.partner'].create({
            'name': 'Destinataire fèves', 'is_company': True})
        cls.site = cls.env['cocoa.reception.site'].create({
            'name': 'Site usinage test', 'site_type': 'external'})
        cls.cert_ra = cls.env['potting.certification'].create({
            'name': 'RA test fèves', 'code': 'RATF', 'suffix': 'RT'})
        cls.ot = cls.env['potting.transit.order'].create({
            'customer_id': cls.customer.id,
            'consignee_id': cls.consignee.id,
            'campaign_id': cls.campaign.id,
            'product_type': 'cocoa_beans',
            'tonnage': 50.0,
        })
        wizard = cls.env['potting.generate.lots.wizard'].with_context(
            active_id=cls.ot.id).create({'transit_order_id': cls.ot.id})
        wizard.max_tonnage_per_lot = 25.0
        wizard.action_generate_lots()
        cls.lot1, cls.lot2 = cls.ot.lot_ids.sorted('id')

    @classmethod
    def _batch(cls, bags=400, gross=26400.0, tare=400.0, ticket=None, cert=None,
               confirm=True):
        batch = cls.env['cocoa.bean.export.batch'].create({
            'site_id': cls.site.id,
            'site_lot_ref': ticket or 'LOT-%s' % bags,
            'weighing_ticket': ticket,
            'bag_count': bags,
            'gross_weight_kg': gross,
            'tare_weight_kg': tare,
            'certification_id': cert.id if cert else False,
        })
        if confirm:
            batch.action_confirm()
        return batch

    def _constitute(self, lot, allocations, complete=False):
        wizard = self.env['cocoa.bean.lot.constitution.wizard'].create({
            'lot_id': lot.id,
            'complete_lot': complete,
            'line_ids': [(0, 0, {'batch_id': batch.id, 'quantity': qty})
                         for batch, qty in allocations],
        })
        wizard.action_confirm()
        lot.invalidate_recordset()
        return wizard


class TestBeanProductType(BeanExportCase):

    def test_01_every_product_type_selection_has_beans(self):
        missing = []
        for model_name, model in self.env.registry.items():
            for name, field in model._fields.items():
                if field.type != 'selection' or not isinstance(field.selection, list):
                    continue
                values = [v for v, _l in field.selection]
                if 'cocoa_mass' in values and 'cocoa_beans' not in values \
                        and (model_name, name) not in EXCLUDED_SELECTIONS:
                    missing.append('%s.%s' % (model_name, name))
        self.assertFalse(missing, "Sélections sans « Fèves de cacao » : %s" % missing)

    def test_02_bean_specs(self):
        Spec = self.env['potting.product.spec']
        self.assertEqual(self.env['potting.customer.invoice']._get_hs_code('cocoa_beans'),
                         '1801.00.00')
        self.assertEqual(Spec.get_value('cocoa_beans', 'nomenclature'), '1801 00 00 00')
        self.assertAlmostEqual(Spec.get_packaging_config('cocoa_beans')['unit_weight'], 0.065)
        self.ICP.set_param('cocoa_bean_export.bag_weight_kg', '62.5')
        self.assertAlmostEqual(Spec.get_packaging_config('cocoa_beans')['unit_weight'], 0.0625)
        self.assertEqual(self.lot1.packaging_unit_name, 'sacs')
        self.assertTrue(self.lot1.name.startswith('F'), self.lot1.name)

    def test_03_beans_only_hides_and_refuses_semi_finished(self):
        selection = dict(self.env['potting.transit.order'].fields_get(
            ['product_type'])['product_type']['selection'])
        self.assertEqual(list(selection), ['cocoa_beans'])
        self.assertEqual(self.env['potting.product.spec'].get_product_types(), ['cocoa_beans'])
        with self.assertRaises(ValidationError):
            self.env['potting.transit.order'].create({
                'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
                'campaign_id': self.campaign.id, 'product_type': 'cocoa_mass', 'tonnage': 10.0})
        # Libellé toujours lisible côté serveur
        self.assertEqual(dict(self.env['potting.transit.order']._fields['product_type']
                              .selection)['cocoa_mass'], 'Masse de cacao')

    def test_04_semi_finished_allowed_when_enabled(self):
        self.ICP.set_param('cocoa_bean_export.with_semi_finished', 'True')
        selection = dict(self.env['potting.transit.order'].fields_get(
            ['product_type'])['product_type']['selection'])
        self.assertIn('cocoa_mass', selection)
        ot = self.env['potting.transit.order'].create({
            'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
            'campaign_id': self.campaign.id, 'product_type': 'cocoa_mass', 'tonnage': 10.0})
        self.assertEqual(ot.product_type, 'cocoa_mass')

    def test_05_factory_menus_follow_the_setting(self):
        Settings = self.env['res.config.settings']
        menu = self.env.ref('potting_management.menu_potting_factory_screen')
        Settings._bean_export_sync_menus()
        self.assertFalse(menu.active)
        self.ICP.set_param('cocoa_bean_export.with_semi_finished', 'True')
        Settings._bean_export_sync_menus()
        self.assertTrue(menu.active)

    def test_06_formule_coefficient_is_one(self):
        Formule = self.env['potting.formule']
        self.assertEqual(Formule._get_bean_coefficient('cocoa_beans'), 1.0)
        self.assertEqual(self.env['potting.lot']._mb_factor('cocoa_beans'), 1.0)

    def test_07_dashboard_shows_beans_card_only(self):
        scope = self.env['potting.dashboard.scope'].build(
            'campaign', campaign_id=self.campaign.id)
        products = self.env['potting.dashboard']._get_product_breakdown(scope)
        cards = [key for key in products if not key.startswith('_')]
        self.assertEqual(cards, ['cocoa_beans'])
        self.assertEqual(products['cocoa_beans']['label'], 'Fèves')


class TestBeanLotConstitution(BeanExportCase):

    def test_10_lot_tonnage_is_the_weighed_net(self):
        batch = self._batch(bags=400, gross=26400.0, tare=400.0, ticket='DS-001')
        self.assertEqual(batch.net_weight_kg, 26000.0)
        self._constitute(self.lot1, [(batch, 400)], complete=True)
        self.assertAlmostEqual(self.lot1.current_tonnage, 26.0, places=6,
                               msg="Poids pesé, pas 400 × 65 kg")
        self.assertAlmostEqual(self.lot1.target_tonnage, 26.0, places=6)
        self.assertEqual(self.lot1.state, 'ready')
        self.assertEqual(self.lot1.current_units, 400)
        self.assertEqual(batch.allocation_status, 'full')
        self.assertEqual(batch.remaining_bags, 0)
        self.assertEqual(self.lot1.bean_batch_ids, batch)
        self.assertEqual(self.lot1.production_line_ids.batch_number, 'DS-001')

    def test_11_last_bags_take_the_exact_remainder(self):
        batch = self._batch(bags=3, gross=200.0, tare=0.0, ticket='DS-ODD')
        # 200 / 3 = 66,667 kg par sac : 1 + 2 sacs doivent refaire 200 kg pile
        self._constitute(self.lot1, [(batch, 1)])
        self._constitute(self.lot2, [(batch, 2)])
        self.assertAlmostEqual(
            sum(batch.production_line_ids.mapped('bean_net_weight_kg')), 200.0, places=2)
        self.assertEqual(batch.remaining_net_kg, 0.0)
        self.assertEqual(batch.allocation_status, 'full')

    def test_12_cannot_overallocate(self):
        batch = self._batch(bags=100, gross=6600.0, tare=100.0, ticket='DS-100')
        with self.assertRaises(UserError):
            self._constitute(self.lot1, [(batch, 101)])
        self._constitute(self.lot1, [(batch, 60)])
        with self.assertRaises(UserError):
            self._constitute(self.lot2, [(batch, 41)])

    def test_13_overfull_lot_requires_complete_flag(self):
        batch = self._batch(bags=420, gross=27720.0, tare=420.0, ticket='DS-420')
        with self.assertRaises(UserError):
            self._constitute(self.lot1, [(batch, 420)])
        self._constitute(self.lot1, [(batch, 420)], complete=True)
        self.assertAlmostEqual(self.lot1.target_tonnage, 27.3, places=6)
        self.assertEqual(self.lot1.state, 'ready')

    def test_14_certification_must_match(self):
        certified = self._batch(bags=10, gross=660.0, tare=10.0, ticket='DS-RA',
                                cert=self.cert_ra)
        with self.assertRaises(ValidationError):
            self._constitute(self.lot1, [(certified, 10)])
        self.lot1.certification_id = self.cert_ra
        self._constitute(self.lot1, [(certified, 10)])
        with self.assertRaises(ValidationError):
            self.lot1.certification_id = False

    def test_15_draft_batch_cannot_be_allocated(self):
        batch = self._batch(bags=10, gross=660.0, tare=10.0, ticket='DS-DRAFT',
                            confirm=False)
        with self.assertRaises(ValidationError):
            self._constitute(self.lot1, [(batch, 10)])

    def test_16_allocated_batch_is_locked(self):
        batch = self._batch(bags=10, gross=660.0, tare=10.0, ticket='DS-LOCK')
        self._constitute(self.lot1, [(batch, 5)])
        with self.assertRaises(UserError):
            batch.gross_weight_kg = 700.0
        with self.assertRaises(UserError):
            batch.action_cancel()
        with self.assertRaises(UserError):
            batch.unlink()

    def test_17_duplicate_weighing_ticket_refused(self):
        self._batch(bags=10, gross=660.0, tare=10.0, ticket='DS-DUP')
        with self.assertRaises(ValidationError):
            self._batch(bags=10, gross=660.0, tare=10.0, ticket='ds-dup')

    def test_18_gross_weight_counts_jute_bags(self):
        self.ICP.set_param('potting_management.tare_cocoa_beans', '1.0')
        batch = self._batch(bags=400, gross=26400.0, tare=400.0, ticket='DS-GROSS')
        self._constitute(self.lot1, [(batch, 400)], complete=True)
        self.assertAlmostEqual(self.lot1.gross_weight_kg, 26400.0, places=2)

    def test_19_bulk_counts_kilograms_without_unit_tare(self):
        self.ICP.set_param('cocoa_bean_export.packaging', 'bulk')
        self.ICP.set_param('potting_management.tare_cocoa_beans', '1.0')
        self.assertEqual(self.env['res.config.settings']
                         .get_packaging_tare_for_product('cocoa_beans'), 0.0)
        ot = self.env['potting.transit.order'].create({
            'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
            'campaign_id': self.campaign.id, 'product_type': 'cocoa_beans',
            'tonnage': 25.0})
        lot = self.env['potting.lot'].create({
            'name': 'VRAC-T1', 'base_name': 'VRAC-T1', 'transit_order_id': ot.id,
            'product_type': 'cocoa_beans', 'target_tonnage': 25.0})
        self.assertEqual(lot.packaging_unit_name, 'kg')
        batch = self._batch(bags=0, gross=24990.0, tare=0.0, ticket='DS-BULK')
        self._constitute(lot, [(batch, 24990)], complete=True)
        self.assertAlmostEqual(lot.current_tonnage, 24.99, places=6)
        self.assertEqual(lot.state, 'ready')

    def test_20_import_accepts_beans_wording(self):
        Spec = self.env['potting.product.spec']
        for text in ('Fèves', 'FEVES DE CACAO', 'cocoa beans', 'cocoa_beans'):
            self.assertEqual(Spec.parse_product_type(text), 'cocoa_beans', text)


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestBeanExportEndToEnd(BeanExportCase):
    """Lot d'usinage → lot export → conteneur → BL → facture export."""

    def test_30_bean_invoice_carries_bean_identity(self):
        from odoo.addons.potting_management.tests.common import get_trimestre
        from odoo.addons.potting_management.tests.common_d6 import set_ot_d6

        self.ICP.set_param('potting_management.tare_cocoa_beans', '1.0')
        batch = self._batch(bags=400, gross=26400.0, tare=400.0, ticket='DS-E2E')
        ot = self.env['potting.transit.order'].create({
            'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
            'campaign_id': self.campaign.id, 'product_type': 'cocoa_beans',
            'tonnage': 26.0})
        wizard = self.env['potting.generate.lots.wizard'].with_context(
            active_id=ot.id).create({'transit_order_id': ot.id})
        wizard.max_tonnage_per_lot = 30.0
        wizard.action_generate_lots()
        lot = ot.lot_ids
        self._constitute(lot, [(batch, 400)], complete=True)
        container = self.env['potting.container'].create({
            'name': 'MSKU1234565', 'container_type': '20'})
        lot.write({'container_id': container.id})
        lot.with_context(bypass_potted_lock=True).sudo().write({'state': 'potted'})

        contract = self.env['potting.customer.order'].create({
            'customer_id': self.customer.id,
            'product_type': 'cocoa_beans',
            'date_order': date.today(),
            'contract_number': 'FEV-CTR-0001',
            'contract_tonnage': 1000.0,
            'unit_price': 2500000,
        })
        self.env['potting.ot.contract.allocation'].create({
            'transit_order_id': ot.id,
            'customer_order_id': contract.id,
            'tonnage_alloue': ot.tonnage,
        })
        cv = self.env['potting.confirmation.vente'].create({
            'reference_ccc': 'CV-FEV-E2E',
            'grade_qualite': 'GF',
            'taux_soutien_reversement': 0.0,
            'campaign_id': self.campaign.id,
            'trimestre_campaign_id': get_trimestre(self.campaign).id,
            'date_emission': date.today() - timedelta(days=10),
            'date_start': date.today() - timedelta(days=10),
            'date_end': date.today() + timedelta(days=80),
            'tonnage_autorise': 5000.0,
            'prix_tonnage': 1500000,
            'product_type': 'cocoa_beans',
            'state': 'active',
        })
        formule = self.env['potting.formule'].create({
            'reference_ccc': 'FO1/FEV/0001',
            'confirmation_vente_id': cv.id,
            'campaign_id': self.campaign.id,
            'product_type': 'cocoa_beans',
            'prix_kg': 1500,
            'prix_tonnage': 1500000,
            'tonnage': 26.0,
            'prix_reference': 1500,
            'transit_order_id': ot.id,
        })
        self.assertEqual(formule.coefficient_conversion, 1.0)
        self.assertEqual(formule.tonnage_converti, 26000.0,
                         "Assiette des taxes : le tonnage de fèves, sans 1,25")
        with self.assertRaises(ValidationError):
            formule.coefficient_conversion = 1.25
        formule.sudo().write({'state': 'paid', 'avant_vente_paye': True})

        bl = self.env['potting.delivery.note'].create({
            'transit_order_id': ot.id,
            'lot_ids': [(6, 0, lot.ids)],
            'bl_external_number': 'BLX-FEV-0001',
            'shipped_weight': 26.0,
            'number_of_bags': 400,
        })
        set_ot_d6(self.env, ot, 1.0, reference='D6-FEV-0001')
        bl.action_confirm()
        ot.sudo().write({'taxes_paid': True, 'state': 'in_progress'})
        ot.invalidate_recordset()
        set_ot_d6(self.env, ot, ot._compute_invoice_amount_xof(
            tonnage=ot.remaining_to_invoice))
        ot._create_invoice(tonnage=ot.remaining_to_invoice)
        invoice = ot.customer_invoice_ids[:1]
        self.assertTrue(invoice)
        self.assertEqual(invoice.hs_code, '1801.00.00')
        self.assertEqual(invoice.get_product_nature_label(), 'FÈVES DE CACAO')
        self.assertEqual(invoice._get_packaging_label(), 'SACS')
        self.assertEqual(invoice._get_packaging_count(), 400)
        self.assertAlmostEqual(invoice.invoiced_tonnage, 26.0, places=3)


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestBeanBatchQuality(BeanExportCase):
    """Qualité : norme d'acceptation + grille des grades du module fèves."""

    def _quality_batch(self, ticket, **measures):
        batch = self._batch(bags=10, gross=660.0, tare=10.0, ticket=ticket,
                            confirm=False)
        batch.write(measures)
        batch.action_confirm()
        return batch

    def test_40_without_measures_not_evaluated(self):
        batch = self._quality_batch('DS-Q0')
        self.assertEqual(batch.quality_status, 'not_evaluated')
        self._constitute(self.lot1, [(batch, 10)])

    def test_41_warn_mode_traces_but_does_not_block(self):
        batch = self._quality_batch('DS-Q1', moisture_pct=7.5, mouldy_pct=7.0)
        self.assertEqual(batch.quality_standard_id,
                         self.env.ref('cocoa_bean_management.quality_standard_ord'))
        self.assertEqual(batch.quality_status, 'non_conform')
        self.assertIn('Moisies', batch.quality_messages)
        self._constitute(self.lot1, [(batch, 10)])
        self.assertIn('Avertissement qualité',
                      ''.join(self.lot1.message_ids.mapped('body')))

    def test_42_block_mode_requires_manager_override(self):
        self.ICP.set_param('cocoa_bean_export.quality_control', 'block')
        batch = self._quality_batch('DS-Q2', moisture_pct=7.5, mouldy_pct=7.0)
        with self.assertRaises(UserError):
            self._constitute(self.lot1, [(batch, 10)])
        # Contournement de l'assistant : la contrainte serveur bloque aussi
        with self.assertRaises(ValidationError):
            self.env['potting.production.line'].create({
                'lot_id': self.lot1.id, 'bean_batch_id': batch.id,
                'bean_net_weight_kg': 650.0, 'units_produced': 10})
        wizard = self.env['cocoa.bean.lot.constitution.wizard'].create({
            'lot_id': self.lot1.id,
            'quality_override': True,
            'quality_override_reason': "Accord écrit de l'acheteur",
            'line_ids': [(0, 0, {'batch_id': batch.id, 'quantity': 10})],
        })
        wizard.action_confirm()
        self.assertEqual(self.lot1.bean_batch_ids, batch)
        self.assertIn("Accord écrit de l'acheteur",
                      ''.join(self.lot1.message_ids.mapped('body')))

    def test_43_grade_grid_compared_to_cv_grade(self):
        campaign = self.env['cocoa.campaign'].create({
            'name': 'Grille test fèves',
            'date_start': date.today() - timedelta(days=30),
            'date_end': date.today() + timedelta(days=30),
            'purchase_price_kg': 0.0,
            'quality_criterion_ids': [(5, 0, 0), (0, 0, {
                'criterion': 'moldy', 'max_g1': 3.0, 'max_g2': 4.0})],
        })
        batch = self._quality_batch('DS-Q3', moisture_pct=7.0, mouldy_pct=3.5)
        self.assertEqual(batch._quality_campaign(), campaign)
        self.assertEqual(batch.quality_grade, 'g2')
        self.assertEqual(batch.quality_status, 'conform')
        from odoo.addons.potting_management.tests.common import get_trimestre
        cv = self.env['potting.confirmation.vente'].create({
            'reference_ccc': 'CV-FEV-GRADE',
            'grade_qualite': 'GF',
            'taux_soutien_reversement': 0.0,
            'campaign_id': self.campaign.id,
            'trimestre_campaign_id': get_trimestre(self.campaign).id,
            'date_emission': date.today() - timedelta(days=10),
            'date_start': date.today() - timedelta(days=10),
            'date_end': date.today() + timedelta(days=80),
            'tonnage_autorise': 5000.0,
            'prix_tonnage': 1500000,
            'product_type': 'cocoa_beans',
            'state': 'active',
        })
        self.ot.sudo().confirmation_vente_id = cv
        issues = batch._quality_issues_for_lot(self.lot1)
        self.assertEqual(len(issues), 1)
        self.assertIn('Grade 2', issues[0])
        cv.sudo().grade_qualite = 'F'
        self.assertFalse(batch._quality_issues_for_lot(self.lot1))

    def test_44_off_mode_skips_control(self):
        self.ICP.set_param('cocoa_bean_export.quality_control', 'off')
        batch = self._quality_batch('DS-Q4', moisture_pct=7.5, mouldy_pct=7.0)
        wizard = self._constitute(self.lot1, [(batch, 10)])
        self.assertFalse(wizard.quality_issues)


GEOJSON_OK = (
    '{"type": "FeatureCollection", "features": ['
    '{"type": "Feature", "properties": {"ProducerName": "Planteur A"},'
    ' "geometry": {"type": "Polygon", "coordinates": [[[-6.5, 5.8], [-6.49, 5.8],'
    ' [-6.49, 5.81], [-6.5, 5.8]]]}},'
    '{"type": "Feature", "properties": {"ProducerName": "Planteur B"},'
    ' "geometry": {"type": "Point", "coordinates": [-6.2, 6.1]}}]}')


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestBeanShipmentDocuments(BeanExportCase):
    """Documents d'export du BL et EUDR des fèves."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.phyto = cls.env.ref('cocoa_bean_export.doc_type_phyto')
        cls.fumigation = cls.env.ref('cocoa_bean_export.doc_type_fumigation')

    def _shipped_bl(self, ticket, cert=None, geojson=None):
        from odoo.addons.potting_management.tests.common_d6 import set_ot_d6
        batch = self._batch(bags=400, gross=26400.0, tare=400.0, ticket=ticket,
                            cert=cert, confirm=False)
        if geojson:
            batch.eudr_geojson = base64.b64encode(geojson.encode())
        batch.action_confirm()
        ot = self.env['potting.transit.order'].create({
            'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
            'campaign_id': self.campaign.id, 'product_type': 'cocoa_beans',
            'tonnage': 26.0})
        lot = self.env['potting.lot'].create({
            'name': 'DOC-%s' % ticket, 'base_name': 'DOC-%s' % ticket,
            'transit_order_id': ot.id, 'product_type': 'cocoa_beans',
            'target_tonnage': 26.0,
            'certification_id': cert.id if cert else False})
        self._constitute(lot, [(batch, 400)], complete=True)
        container = self.env['potting.container'].create({
            'name': 'CONT-%s' % ticket, 'container_type': '20'})
        lot.write({'container_id': container.id})
        lot.with_context(bypass_potted_lock=True).sudo().write({'state': 'potted'})
        contract = self.env['potting.customer.order'].create({
            'customer_id': self.customer.id, 'product_type': 'cocoa_beans',
            'date_order': date.today(), 'contract_number': 'CTR-%s' % ticket,
            'contract_tonnage': 1000.0, 'unit_price': 2500000})
        self.env['potting.ot.contract.allocation'].create({
            'transit_order_id': ot.id, 'customer_order_id': contract.id,
            'tonnage_alloue': ot.tonnage})
        bl = self.env['potting.delivery.note'].create({
            'transit_order_id': ot.id,
            'lot_ids': [(6, 0, lot.ids)],
            'bl_external_number': 'BLX-%s' % ticket,
            'shipped_weight': 26.0,
            'number_of_bags': 400,
        })
        set_ot_d6(self.env, ot, 1.0, reference='D6-%s' % ticket)
        return bl, batch, lot

    def _fill(self, bl, doc_type, days_ago=0, attach=True):
        doc = bl.bean_document_ids.filtered(lambda d: d.type_id == doc_type)
        vals = {'number': '%s-001' % doc_type.code,
                'date': date.today() - timedelta(days=days_ago)}
        if attach:
            vals['attachment_ids'] = [(0, 0, {
                'name': '%s.pdf' % doc_type.code,
                'datas': base64.b64encode(b'%PDF-1.4 test')})]
        doc.write(vals)
        return doc

    def test_50_bl_receives_applicable_document_lines(self):
        bl, _batch, _lot = self._shipped_bl('DOC-50')
        types = bl.bean_document_ids.mapped('type_id')
        self.assertIn(self.phyto, types)
        self.assertNotIn(self.env.ref('cocoa_bean_export.doc_type_transaction'), types,
                         "Certificat de transaction : lots certifiés seulement")
        self.assertTrue(all(d.status == 'missing' for d in bl.bean_document_ids))

    def test_51_bl_confirmation_requires_bl_documents(self):
        self.phyto.requirement = 'bl'
        bl, _batch, _lot = self._shipped_bl('DOC-51')
        with self.assertRaises(UserError):
            bl.action_confirm()
        doc = self._fill(bl, self.phyto, attach=False)
        self.assertEqual(doc.status, 'incomplete', "Pièce jointe exigée")
        with self.assertRaises(UserError):
            bl.action_confirm()
        self._fill(bl, self.phyto)
        self.assertEqual(doc.status, 'ok')
        bl.action_confirm()
        self.assertEqual(bl.state, 'confirmed')

    def test_52_validity_before_shipment(self):
        self.fumigation.write({'requirement': 'bl', 'validity_days': 10})
        bl, _batch, _lot = self._shipped_bl('DOC-52')
        bl.date_shipment = date.today()
        doc = self._fill(bl, self.fumigation, days_ago=20)
        self.assertEqual(doc.status, 'expired')
        with self.assertRaises(UserError):
            bl.action_confirm()
        self._fill(bl, self.fumigation, days_ago=3)
        self.assertEqual(doc.status, 'ok')

    def test_53_invoice_confirmation_requires_invoice_documents(self):
        bl, _batch, lot = self._shipped_bl('DOC-53')
        bl.action_confirm()
        invoice = self.env['potting.customer.invoice'].create({
            'partner_id': self.customer.id,
            'transit_order_id': bl.transit_order_id.id,
            'delivery_note_id': bl.id,
            'invoiced_tonnage': 26.0,
            'currency_id': get_xof(self.env).id,
        })
        with self.assertRaises(UserError):
            invoice.write({'state': 'confirmed'})
        for doc_type in bl.bean_document_ids.mapped('type_id').filtered(
                lambda t: t.requirement != 'optional'):
            self._fill(bl, doc_type)
        self.assertTrue(bl.bean_documents_complete)
        invoice.write({'state': 'confirmed'})
        self.assertEqual(invoice.state, 'confirmed')

    def test_60_eudr_from_supplied_geojson(self):
        bl, batch, lot = self._shipped_bl('EUDR-60', geojson=GEOJSON_OK)
        self.assertEqual(batch.eudr_feature_count, 2)
        self.assertEqual(batch.eudr_state, 'pending')
        self.assertEqual(lot.eudr_state, 'pending')
        with self.assertRaises(UserError):
            bl.action_generate_eudr_dossier()
        batch.action_eudr_verify()
        self.assertEqual(batch.eudr_state, 'eligible')
        lot.invalidate_recordset(['eudr_state'])
        bl.invalidate_recordset(['eudr_state'])
        self.assertEqual(lot.eudr_state, 'eligible')
        self.assertEqual(bl.eudr_state, 'eligible')
        collection, _beans, _plots = bl._eudr_feature_collection()
        self.assertEqual(len(collection['features']), 2)
        bl.action_generate_eudr_dossier()
        self.assertEqual(bl.eudr_plot_count, 2)

    def test_61_new_geojson_needs_new_verification(self):
        batch = self._batch(bags=10, gross=660.0, tare=10.0, ticket='EUDR-61', confirm=False)
        batch.eudr_geojson = base64.b64encode(GEOJSON_OK.encode())
        batch.action_eudr_verify()
        self.assertTrue(batch.eudr_verified)
        batch.eudr_geojson = base64.b64encode(GEOJSON_OK.replace('Planteur B', 'C').encode())
        self.assertFalse(batch.eudr_verified)
        self.assertEqual(batch.eudr_state, 'pending')

    def test_62_invalid_geojson_refused(self):
        batch = self._batch(bags=10, gross=660.0, tare=10.0, ticket='EUDR-62', confirm=False)
        for bad in ('pas du json',
                    '{"type": "FeatureCollection", "features": []}',
                    # latitude / longitude inversées : hors Côte d'Ivoire
                    GEOJSON_OK.replace('[-6.2, 6.1]', '[6.1, -6.2]'),
                    # polygone non fermé
                    GEOJSON_OK.replace('[-6.49, 5.81], [-6.5, 5.8]]', '[-6.49, 5.81], [-6.48, 5.8]]')):
            with self.assertRaises(ValidationError, msg=bad[:30]):
                batch.eudr_geojson = base64.b64encode(bad.encode())
                batch.flush_recordset()
        self.assertEqual(batch.eudr_state, 'not_traced')


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestBeanBatchImport(BeanExportCase):

    def _xlsx(self, rows):
        import io
        import openpyxl
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return base64.b64encode(buffer.getvalue())

    def test_70_import_with_aliases_and_errors(self):
        data = self._xlsx([
            # Ordre libre, alias, accents et casse indifférents
            ['Date', 'Lots', 'SITE', 'Bulletin', 'Nombre de sacs', 'Brut', 'Tare',
             'Certif', 'Grade', 'Humidité'],
            ['24/10/2026', '5011', 'Site usinage test', 'DS-IMP-1', 400, '26 400,5', 400.5,
             'rt', 'Grade 1', '7,2'],
            ['24/10/2026', '5012', 'Site inconnu', 'DS-IMP-2', 10, 660, 10, None, None, None],
            ['24/10/2026', '5011', 'Site usinage test', 'DS-IMP-1', 400, 26400, 400,
             None, None, None],
            ['25/10/2026', '5013', 'Site usinage test', 'DS-IMP-3', 10, 600, 700,
             None, None, None],
            [None, None, None, None, None, None, None, None, None, None],
        ])
        wizard = self.env['cocoa.bean.export.batch.import.wizard'].create({
            'file_data': data, 'file_name': 'historique.xlsx', 'confirm_batches': True})
        wizard.action_parse_file()
        self.assertEqual(len(wizard.line_ids), 4, "Ligne vide ignorée")
        by_row = {line.row_number: line for line in wizard.line_ids}
        self.assertEqual(by_row[2].status, 'ok', by_row[2].errors)
        self.assertIn('inconnu', by_row[3].errors)
        self.assertIn('doublon', by_row[4].errors)
        self.assertIn('tare', by_row[5].errors)
        wizard.action_import()
        batch = self.env['cocoa.bean.export.batch'].search([('weighing_ticket', '=', 'DS-IMP-1')])
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch.state, 'confirmed')
        self.assertEqual(batch.net_weight_kg, 26000.0)
        self.assertEqual(batch.certification_id, self.cert_ra)
        self.assertEqual(batch.grade, 'GF')
        self.assertEqual(batch.moisture_pct, 7.2)
        self.assertEqual(batch.date, date(2026, 10, 24))
        self.assertEqual(wizard.state, 'done')

    def test_71_missing_required_column_is_explained(self):
        data = self._xlsx([['Lots', 'Site'], ['5011', 'Site usinage test']])
        wizard = self.env['cocoa.bean.export.batch.import.wizard'].create({
            'file_data': data, 'file_name': 'incomplet.xlsx'})
        with self.assertRaises(UserError) as error:
            wizard.action_parse_file()
        self.assertIn('Poids brut', str(error.exception))

    def test_72_create_missing_sites(self):
        data = self._xlsx([['N° lot site', "Site d'usinage", 'Date', 'Poids brut (kg)'],
                           ['9001', 'Nouveau site', '20/10/2026', 1000]])
        wizard = self.env['cocoa.bean.export.batch.import.wizard'].create({
            'file_data': data, 'file_name': 'sites.xlsx', 'create_missing_sites': True})
        wizard.action_parse_file()
        wizard.action_import()
        batch = self.env['cocoa.bean.export.batch'].search([('site_lot_ref', '=', '9001')])
        self.assertEqual(batch.site_id.name, 'Nouveau site')
        self.assertEqual(batch.state, 'draft')

    def test_73_template_downloads(self):
        wizard = self.env['cocoa.bean.export.batch.import.wizard'].create({})
        action = wizard.action_download_template()
        self.assertTrue(wizard.template_file)
        self.assertIn('download=true', action['url'])
