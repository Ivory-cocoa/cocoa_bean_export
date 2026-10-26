# -*- coding: utf-8 -*-
"""Société qui exporte À LA FOIS des fèves et des semi-finis.

Ce que ces tests verrouillent :
  * les filières sont propres à chaque société de la base : un document
    d'une filière que sa société n'exporte pas est refusé, et une filière ne
    se retire pas tant que des documents y sont en cours ;
  * un utilisateur ne voit que les documents de ses filières (règles
    d'accès), et rien sans filière ; une CV « Tous produits » est visible des
    deux filières mais n'en sert qu'une ;
  * les fèves du magasin de l'usine sont réservées par une sortie export en
    brouillon (la production ne les prend plus), consommées à la
    confirmation (stock, Mass Balance une seule fois), rendues à
    l'annulation ;
  * les tableaux de bord ne comptent que les filières de l'utilisateur, même
    en sudo, et proposent « Fèves / Semi-finis / Tout » quand il voit les
    deux ;
  * la migration du réglage global garde l'activité de chaque société et
    les accès de chaque utilisateur.
"""

from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.cocoa_bean_export.hooks import (migrate_from_global_setting,
                                                 setup_export_families)
from odoo.addons.potting_management.tests.common import get_trimestre

from .test_bean_export import BeanExportCase

BEANS_GROUP = 'cocoa_bean_export.group_bean_export_beans'
SEMI_GROUP = 'cocoa_bean_export.group_bean_export_semi_finished'
MANAGER = 'potting_management.group_potting_manager'


class MixedExportCase(BeanExportCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({'export_beans': True, 'export_semi_finished': True})
        cls.semi_ot = cls.env['potting.transit.order'].create({
            'customer_id': cls.customer.id,
            'consignee_id': cls.consignee.id,
            'campaign_id': cls.campaign.id,
            'product_type': 'cocoa_butter',
            'tonnage': 20.0,
        })
        cls.beans_user = cls._user('mixte_feves', BEANS_GROUP)
        cls.semi_user = cls._user('mixte_semi', SEMI_GROUP)
        cls.both_user = cls._user('mixte_tout', '%s,%s' % (BEANS_GROUP, SEMI_GROUP))

    @classmethod
    def _user(cls, login, family_groups):
        return new_test_user(
            cls.env, login=login, groups='base.group_user,%s,%s' % (MANAGER, family_groups),
            company_id=cls.env.company.id, company_ids=[(6, 0, cls.env.company.ids)])

    def _cv(self, reference):
        return self.env['potting.confirmation.vente'].create({
            'reference_ccc': reference,
            'grade_qualite': 'GF',
            'taux_soutien_reversement': 0.0,
            'campaign_id': self.campaign.id,
            'trimestre_campaign_id': get_trimestre(self.campaign).id,
            'date_emission': date.today() - timedelta(days=10),
            'date_start': date.today() - timedelta(days=10),
            'date_end': date.today() + timedelta(days=80),
            'tonnage_autorise': 500.0,
            'prix_tonnage': 1500000,
            'product_type': 'all',
            'state': 'active',
        })


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestCompanyFamilies(MixedExportCase):

    def test_200_a_company_exports_at_least_one_family(self):
        with self.assertRaises(ValidationError):
            self.env.company.write({'export_beans': False, 'export_semi_finished': False})

    def test_201_document_follows_its_own_company(self):
        other = self.env['res.company'].create({
            'name': 'Transformateur seul', 'export_beans': False,
            'export_semi_finished': True})
        OT = self.env['potting.transit.order']
        OT.new({'product_type': 'cocoa_mass', 'company_id': other.id}) \
            ._check_bean_product_type_active()
        with self.assertRaisesRegex(ValidationError, "n'exporte pas"):
            OT.new({'product_type': 'cocoa_beans', 'company_id': other.id}) \
                ._check_bean_product_type_active()
        # Même document dans la société mixte : accepté
        OT.new({'product_type': 'cocoa_beans', 'company_id': self.env.company.id}) \
            ._check_bean_product_type_active()

    def test_202_family_with_open_documents_cannot_be_dropped(self):
        with self.assertRaisesRegex(ValidationError, 'en cours'):
            self.env.company.export_beans = False
        self.env['potting.transit.order'].search([
            ('product_type', '=', 'cocoa_beans'),
            ('company_id', '=', self.env.company.id)]).sudo().write({'state': 'cancelled'})
        self.env.company.export_beans = False
        self.assertFalse(self.env.company.export_beans)

    def test_203_choices_follow_the_user_families(self):
        def choices(user):
            return [value for value, _label in self.env['potting.transit.order'].with_user(
                user).fields_get(['product_type'])['product_type']['selection']]
        self.assertEqual(choices(self.beans_user), ['cocoa_beans'])
        self.assertNotIn('cocoa_beans', choices(self.semi_user))
        self.assertIn('cocoa_mass', choices(self.semi_user))
        self.assertEqual(set(choices(self.both_user)),
                         {'cocoa_beans', 'cocoa_mass', 'cocoa_butter', 'cocoa_cake',
                          'cocoa_powder'})

    def test_204_new_internal_user_receives_the_company_families(self):
        user = new_test_user(self.env, login='mixte_nouveau', groups='base.group_user')
        self.assertTrue(user.has_group(BEANS_GROUP))
        self.assertTrue(user.has_group(SEMI_GROUP))
        restricted = new_test_user(self.env, login='mixte_restreint',
                                   groups='base.group_user,%s' % SEMI_GROUP)
        self.assertFalse(restricted.has_group(BEANS_GROUP), "Choix explicite respecté")


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestFamilyRights(MixedExportCase):

    def test_210_each_user_sees_only_his_families(self):
        OT = self.env['potting.transit.order']
        both = OT.search([('id', 'in', (self.ot | self.semi_ot).ids)])
        self.assertEqual(OT.with_user(self.beans_user).search([('id', 'in', both.ids)]), self.ot)
        self.assertEqual(OT.with_user(self.semi_user).search([('id', 'in', both.ids)]),
                         self.semi_ot)
        self.assertEqual(OT.with_user(self.both_user).search([('id', 'in', both.ids)]), both)
        lots = self.env['potting.lot'].with_user(self.semi_user).search(
            [('id', 'in', self.ot.lot_ids.ids)])
        self.assertFalse(lots, "Lots de fèves invisibles de la filière semi-finis")
        with self.assertRaises(AccessError):
            self.ot.with_user(self.semi_user).read(['name'])

    def test_211_user_without_family_sees_nothing(self):
        user = self._user('mixte_aucune', BEANS_GROUP)
        user.groups_id = [(3, self.env.ref(BEANS_GROUP).id)]
        self.assertFalse(self.env['potting.transit.order'].with_user(user).search(
            [('id', 'in', (self.ot | self.semi_ot).ids)]))

    def test_212_user_cannot_create_in_another_family(self):
        with self.assertRaises(AccessError):
            self.env['potting.transit.order'].with_user(self.beans_user).create({
                'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
                'campaign_id': self.campaign.id, 'product_type': 'cocoa_mass',
                'tonnage': 5.0})

    def test_213_all_products_cv_is_visible_from_both_families(self):
        cv = self._cv('CV-MIXTE-VIS')
        for user in (self.beans_user, self.semi_user):
            self.assertEqual(self.env['potting.confirmation.vente'].with_user(user).search(
                [('id', '=', cv.id)]), cv)

    def test_215_factory_documents_belong_to_semi_finished(self):
        Rule = self.env['ir.rule']
        for model in ('potting.production.order', 'potting.local.sale'):
            beans = Rule.with_user(self.beans_user)._compute_domain(model, 'read')
            semi = Rule.with_user(self.semi_user)._compute_domain(model, 'read')
            self.assertIn((0, '=', 1), beans, "Pas d'usine pour la filière fèves")
            self.assertNotIn((0, '=', 1), semi)
            # L'isolement entre sociétés n'est jamais élargi
            self.assertIn(('company_id', 'in', self.env.company.ids), semi, model)
        # Les CV de déblocage restent communes (prix de référence des CV)
        self.assertNotIn((0, '=', 1), Rule.with_user(self.beans_user)._compute_domain(
            'potting.cv.deblocage', 'read'))

    def test_214_bean_batches_are_beans_only(self):
        batch = self._batch(ticket='DS-DROITS')
        Batch = self.env['cocoa.bean.export.batch']
        self.assertFalse(Batch.with_user(self.semi_user).search([('id', '=', batch.id)]))
        self.assertEqual(Batch.with_user(self.beans_user).search([('id', '=', batch.id)]),
                         batch)


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestCvSingleFamily(MixedExportCase):

    def _formule(self, cv, reference, product_type):
        return self.env['potting.formule'].create({
            'reference_ccc': reference,
            'confirmation_vente_id': cv.id,
            'campaign_id': self.campaign.id,
            'prix_kg': 1500,
            'prix_tonnage': 1500000,
            'prix_reference': 1500,
            'tonnage': 20.0,
            'product_type': product_type,
        })

    def test_220_all_products_cv_serves_one_family(self):
        cv = self._cv('CV-MIXTE-UNE')
        self._formule(cv, 'FO1/MIX/1', 'cocoa_beans')
        self._formule(cv, 'FO1/MIX/2', 'cocoa_beans')
        with self.assertRaisesRegex(ValidationError, 'une filière'):
            self._formule(cv, 'FO1/MIX/3', 'cocoa_butter')

    def test_221_cancelled_formule_frees_the_cv(self):
        cv = self._cv('CV-MIXTE-LIBRE')
        formule = self._formule(cv, 'FO1/MIX/A', 'cocoa_beans')
        formule.sudo().write({'state': 'cancelled'})
        self.assertTrue(self._formule(cv, 'FO1/MIX/B', 'cocoa_butter'))


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestWarehouseExit(MixedExportCase):
    """Fèves du magasin de l'usine : réservées, consommées, rendues."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cooperative = cls.env['cocoa.bean.cooperative'].create({
            'name': 'COOP MIXTE', 'code': 'CMIX', 'region': 'Indénié-Djuablin'})
        cls.warehouse = cls.env['cocoa.bean.warehouse'].create({
            'name': 'Magasin usine', 'code': 'WMIX'})
        cls.ra = cls.env.ref('cocoa_bean_management.certification_rainforest')
        cls.cert_ra.cocoa_certification_id = cls.ra

    def _stock_lot(self, tonnes=30.0, kind='export', certified=False):
        vals = {
            'cooperative_id': self.cooperative.id,
            'warehouse_id': self.warehouse.id,
            'quantity': tonnes,
            'purchase_price': tonnes * 1_500_000,
            'cocoa_kind': kind,
        }
        if certified:
            vals.update(certification_id=self.ra.id, traceability='certified')
        lot = self.env['cocoa.bean.lot'].create(vals)
        lot.state = 'available'
        return lot

    def _exit(self, lots_and_tonnes, gross=26400.0, tare=400.0, confirm=True):
        batch = self.env['cocoa.bean.export.batch'].create({
            'origin': 'warehouse',
            'warehouse_id': self.warehouse.id,
            'bag_count': 400,
            'gross_weight_kg': gross,
            'tare_weight_kg': tare,
            'stock_line_ids': [(0, 0, {'bean_lot_id': lot.id, 'quantity_t': tonnes})
                               for lot, tonnes in lots_and_tonnes],
        })
        if confirm:
            batch.action_confirm()
        return batch

    def test_230_draft_exit_reserves_the_beans(self):
        lot = self._stock_lot(30.0)
        batch = self._exit([(lot, 26.0)], confirm=False)
        self.assertAlmostEqual(lot._pool_reserved_t().get(lot.id), 26.0, places=3)
        self.assertNotIn(lot.id, lot._pool_reserved_t(exclude=batch),
                         "La sortie ne se réserve pas contre elle-même")
        self.assertAlmostEqual(batch.stock_line_ids.free_t, 30.0, places=3)

    def test_231_confirmation_consumes_the_stock(self):
        lot = self._stock_lot(30.0)
        batch = self._exit([(lot, 26.0)])
        self.assertEqual(batch.state, 'confirmed')
        self.assertAlmostEqual(lot.available_quantity, 4.0, places=3)
        self.assertEqual(lot.state, 'partial')
        consumption = batch.stock_line_ids.consumption_id
        self.assertEqual(consumption.state, 'confirmed')
        self.assertEqual(consumption.export_batch_id, batch)
        self.assertFalse(lot._pool_reserved_t().get(lot.id), "Consommé, plus réservé")
        self.assertEqual(batch._eudr_source_lots(), lot, "Source EUDR : le lot prélevé")
        self.assertEqual(batch.site_lot_ref, batch.name)
        self.assertAlmostEqual(batch.stock_gap_kg, 0.0, places=2)
        # Le lot export se constitue comme depuis un site
        self._constitute(self.lot1, [(batch, 400)], complete=True)
        self.assertAlmostEqual(self.lot1.current_tonnage, 26.0, places=6)

    def test_232_cancellation_gives_the_stock_back(self):
        lot = self._stock_lot(30.0)
        batch = self._exit([(lot, 26.0)])
        batch.action_cancel()
        self.assertAlmostEqual(lot.available_quantity, 30.0, places=3)
        self.assertEqual(lot.state, 'available')
        self.assertFalse(batch.stock_line_ids.consumption_id)

    def test_233_reserved_beans_cannot_be_taken_twice(self):
        lot = self._stock_lot(30.0)
        self._exit([(lot, 20.0)], confirm=False)
        with self.assertRaisesRegex(UserError, 'libres'):
            self._exit([(lot, 20.0)], gross=20400.0)

    def test_234_bush_cocoa_is_refused(self):
        lot = self._stock_lot(30.0, kind='brousse')
        with self.assertRaisesRegex(UserError, 'brousse'):
            self._exit([(lot, 26.0)])

    def test_235_certified_beans_debit_mass_balance_once(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('cocoa_bean_management.mb_debit_start_date',
                         fields.Date.to_string(fields.Date.today() - timedelta(days=30)))
        Entry = self.env['cocoa.mb.entry']
        Entry.create({'certification_id': self.ra.id, 'entry_type': 'adjustment',
                      'quantity_kg': 40000.0,
                      'date': fields.Date.today() - timedelta(days=30)})
        lot = self._stock_lot(30.0, certified=True)
        batch = self._exit([(lot, 26.0)])
        self.assertEqual(batch.certification_id.cocoa_certification_id, self.ra,
                         "Certification export déduite des fèves prélevées")
        self.assertFalse(batch.mb_entry_ids, "Pas de second débit côté export")
        self.assertAlmostEqual(Entry._balance(self.ra, self.env.company), 14000.0, places=2)
        batch.action_cancel()
        self.assertAlmostEqual(Entry._balance(self.ra, self.env.company), 40000.0, places=2)

    def test_236_mixed_certifications_refused(self):
        ordinary = self._stock_lot(10.0)
        certified = self._stock_lot(10.0, certified=True)
        with self.assertRaisesRegex(UserError, 'certifications'):
            self._exit([(ordinary, 10.0), (certified, 10.0)], gross=20400.0)


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestDashboardFamilies(MixedExportCase):

    def _scope_for(self, user, family=None):
        return self.env['potting.dashboard.scope'].with_user(user).build(
            'campaign', campaign_id=self.campaign.id, product_family=family)

    def test_240_choice_offered_only_with_both_families(self):
        Scope = self.env['potting.dashboard.scope']
        types, family, options = Scope.with_user(self.both_user).resolve_product_family()
        self.assertIsNone(types, "Tout est visible : aucune restriction")
        self.assertEqual([o['key'] for o in options], ['all', 'beans', 'semi_finished'])
        types, family, options = Scope.with_user(self.beans_user).resolve_product_family(
            'semi_finished')
        self.assertEqual(types, ['cocoa_beans'], "Une filière non accordée ne s'obtient pas")
        self.assertFalse(options)

    def test_241_sudo_dashboard_counts_only_the_user_families(self):
        Dashboard = self.env['potting.dashboard']
        for user, expected in ((self.beans_user, {'cocoa_beans'}),
                               (self.semi_user, {'cocoa_mass', 'cocoa_butter',
                                                 'cocoa_cake', 'cocoa_powder'})):
            scope = self._scope_for(user)
            OT = self.env['potting.transit.order'].sudo()
            found = OT.search(scope.domain('potting.transit.order',
                                           [('id', 'in', (self.ot | self.semi_ot).ids)]))
            self.assertTrue(found)
            self.assertLessEqual(set(found.mapped('product_type')), expected)
            products = Dashboard.with_user(user).sudo()._get_product_breakdown(scope)
            self.assertEqual({k for k in products if not k.startswith('_')}, expected)

    def test_242_filter_beans_or_semi_finished(self):
        ids = (self.ot | self.semi_ot).ids
        OT = self.env['potting.transit.order'].sudo()
        beans = self._scope_for(self.both_user, 'beans')
        semi = self._scope_for(self.both_user, 'semi_finished')
        self.assertEqual(OT.search(beans.domain('potting.transit.order', [('id', 'in', ids)])),
                         self.ot)
        self.assertEqual(OT.search(semi.domain('potting.transit.order', [('id', 'in', ids)])),
                         self.semi_ot)
        # Déblocages et ventes locales : activité d'usine, hors filière fèves
        self.assertEqual(beans.product_domain('potting.local.sale'), [(0, '=', 1)])
        self.assertFalse(semi.product_domain('potting.local.sale'))

    def test_243_the_three_dashboards_take_the_family(self):
        data = self.env['potting.dashboard'].with_user(self.both_user).get_dashboard_data(
            'campaign', None, None, self.campaign.id, None, 'beans')
        self.assertNotIn('error', data)
        self.assertEqual(data['scope']['product_family'], 'beans')
        self.assertEqual(len(data['scope']['product_family_options']), 3)
        self.assertEqual({k for k in data['products'] if not k.startswith('_')},
                         {'cocoa_beans'})
        cv_data = self.env['potting.dashboard.cv'].with_user(self.both_user) \
            .get_cv_dashboard_data(self.campaign.id, 'semi_finished')
        self.assertNotIn('error', cv_data)
        self.assertEqual(cv_data['product_family'], 'semi_finished')
        finance = self.env['potting.dashboard.finance'].with_user(self.both_user) \
            .get_finance_data(self.campaign.id, 'product', 'beans')
        self.assertNotIn('error', finance)
        self.assertEqual(finance['product_family'], 'beans')
        self.assertIn('kpis', finance)

    def test_244_unknown_family_falls_back_to_everything(self):
        data = self.env['potting.dashboard'].with_user(self.both_user).get_dashboard_data(
            'campaign', None, None, self.campaign.id, None, 'nimporte')
        self.assertEqual(data['scope']['product_family'], 'all')


@tagged('cocoa_bean_export', 'post_install', '-at_install')
class TestFamiliesMigration(BeanExportCase):

    def test_250_legacy_setting_becomes_company_families(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('cocoa_bean_export.with_semi_finished', 'True')
        user = new_test_user(self.env, login='migration_user', groups='base.group_user')
        user.groups_id = [(3, self.env.ref(BEANS_GROUP).id), (3, self.env.ref(SEMI_GROUP).id)]
        migrate_from_global_setting(self.env)
        self.assertTrue(self.env.company.export_beans)
        self.assertTrue(self.env.company.export_semi_finished)
        self.assertTrue(user.has_group(BEANS_GROUP) and user.has_group(SEMI_GROUP),
                        "Personne ne perd l'accès le jour de la mise à jour")
        self.assertFalse(ICP.get_param('cocoa_bean_export.with_semi_finished'))

    def test_251_legacy_beans_only_keeps_beans_only(self):
        self.env.company.write({'export_beans': True, 'export_semi_finished': True})
        self.env['potting.transit.order'].search([
            ('company_id', '=', self.env.company.id),
            ('product_type', '!=', 'cocoa_beans')]).sudo().write({'state': 'cancelled'})
        self.env['potting.customer.order'].search([
            ('company_id', '=', self.env.company.id),
            ('product_type', '!=', 'cocoa_beans')]).sudo().write({'state': 'cancelled'})
        has_semi_docs = any(self.env[model].sudo().search_count([
            ('company_id', '=', self.env.company.id),
            ('product_type', 'not in', ('cocoa_beans', 'all', False))], limit=1)
            for model in ('potting.customer.order', 'potting.transit.order',
                          'potting.confirmation.vente', 'potting.formule'))
        migrate_from_global_setting(self.env)
        self.assertTrue(self.env.company.export_beans)
        self.assertEqual(self.env.company.export_semi_finished, has_semi_docs,
                         "Semi-finis gardés seulement s'il y en a des documents")

    def test_252_install_in_a_semi_finished_base_keeps_semi_finished(self):
        self.env.company.write({'export_beans': True, 'export_semi_finished': True})
        self.env['potting.transit.order'].create({
            'customer_id': self.customer.id, 'consignee_id': self.consignee.id,
            'campaign_id': self.campaign.id, 'product_type': 'cocoa_mass', 'tonnage': 5.0})
        beans_docs = self.env['potting.transit.order'].sudo().search_count([
            ('company_id', '=', self.env.company.id), ('product_type', '=', 'cocoa_beans')])
        setup_export_families(self.env)
        self.assertTrue(self.env.company.export_semi_finished)
        self.assertEqual(self.env.company.export_beans, bool(beans_docs),
                         "Comme ICP : les fèves ne s'activent pas toutes seules")
