# -*- coding: utf-8 -*-
"""Fèves exportées depuis le magasin de l'usine.

Une société qui transforme ET exporte des fèves brutes prend une partie de
son stock (lots « cacao export », usinés et ensachés) pour l'export. Le lot
d'usinage reste la porte unique des lots export : il prend ici l'origine
« Magasin de l'usine » et porte les lots de fèves prélevés.

  * Brouillon : les quantités prélevées sont RÉSERVÉES — l'engagement par
    tonnage et les ordres de production ne les désignent plus
    (``cocoa.bean.lot._pool_reserved_t``) ;
  * Confirmation : chaque prélèvement devient une consommation de fèves
    confirmée — le stock baisse et, pour un lot certifié, le registre Mass
    Balance est débité par le module fèves (jamais deux fois) ;
  * Annulation : les consommations sont annulées, le stock et le registre
    reviennent à l'état d'avant.

La pesée de sortie (brut, tare, net) fait toujours foi pour le tonnage
exporté ; l'écart avec le stock prélevé est affiché.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round

# Tolérance de comparaison des tonnages (1 kg)
_T_PRECISION = 3


class CocoaBeanExportBatchStock(models.Model):
    _inherit = 'cocoa.bean.export.batch'

    origin = fields.Selection([
        ('site', "Site d'usinage"),
        ('warehouse', "Magasin de l'usine"),
    ], string="Origine", default='site', required=True, tracking=True,
        help="Site d'usinage : fèves usinées au site, du site au port.\n"
             "Magasin de l'usine : fèves prélevées dans le stock de l'usine "
             "(le stock baisse à la confirmation).")
    # Le site n'est exigé que pour l'origine « site » (contrainte ci-dessous)
    site_id = fields.Many2one(required=False)
    site_lot_ref = fields.Char(required=False)
    warehouse_id = fields.Many2one(
        'cocoa.bean.warehouse', string="Magasin", tracking=True,
        check_company=True, domain="[('company_id', 'in', (company_id, False))]",
        help="Magasin de l'usine dont sortent les fèves.")
    stock_line_ids = fields.One2many(
        'cocoa.bean.export.batch.stock.line', 'batch_id',
        string="Lots de fèves prélevés", copy=False)
    stock_quantity_kg = fields.Float(
        string="Prélevé sur le stock (kg)", digits=(16, 2),
        compute='_compute_stock_quantity', store=True)
    stock_gap_kg = fields.Float(
        string="Écart pesée − stock (kg)", digits=(16, 2),
        compute='_compute_stock_quantity', store=True,
        help="Poids net pesé à la sortie moins la quantité prélevée sur les "
             "lots : le tonnage exporté est le poids pesé.")

    @api.depends('stock_line_ids.quantity_t', 'net_weight_kg', 'origin')
    def _compute_stock_quantity(self):
        for batch in self:
            if batch.origin != 'warehouse':
                batch.stock_quantity_kg = batch.stock_gap_kg = 0.0
                continue
            stock_kg = float_round(
                sum(batch.stock_line_ids.mapped('quantity_t')) * 1000.0,
                precision_digits=2)
            batch.stock_quantity_kg = stock_kg
            batch.stock_gap_kg = float_round(
                (batch.net_weight_kg or 0.0) - stock_kg, precision_digits=2)

    @api.depends('name', 'site_lot_ref', 'site_id', 'origin', 'warehouse_id')
    def _compute_display_name(self):
        super()._compute_display_name()
        for batch in self.filtered(lambda b: b.origin == 'warehouse'):
            batch.display_name = " — ".join(p for p in (
                batch.name or '', batch.warehouse_id.name or _("magasin")) if p)

    @api.constrains('origin', 'site_id', 'site_lot_ref', 'warehouse_id')
    def _check_origin(self):
        for batch in self:
            if batch.origin == 'site':
                if not batch.site_id or not batch.site_lot_ref:
                    raise ValidationError(_(
                        "Lot d'usinage %s : indiquez le site d'usinage et le n° "
                        "de lot du site.", batch.name))
            elif not batch.warehouse_id:
                raise ValidationError(_(
                    "Lot d'usinage %s : indiquez le magasin de l'usine.", batch.name))
            if batch.origin == 'warehouse' and batch.processing_id:
                raise ValidationError(_(
                    "Lot d'usinage %s : une sortie du magasin ne se rattache "
                    "pas à un usinage de site.", batch.name))

    def write(self, vals):
        if {'origin', 'warehouse_id'} & set(vals):
            if self.filtered(lambda b: b.state != 'draft'):
                raise UserError(_(
                    "L'origine et le magasin d'un lot d'usinage ne changent "
                    "qu'en brouillon."))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Confirmation : le stock baisse
    # ------------------------------------------------------------------
    def action_confirm(self):
        to_consume = self.filtered(lambda b: b.state == 'draft' and b.origin == 'warehouse')
        for batch in to_consume:
            batch._check_stock_lines_before_confirm()
        result = super().action_confirm()
        for batch in to_consume.filtered(lambda b: b.state == 'confirmed'):
            batch._consume_stock_lines()
        return result

    def _check_stock_lines_before_confirm(self):
        self.ensure_one()
        lines = self.stock_line_ids
        if not lines:
            raise UserError(_(
                "Lot d'usinage %s : indiquez les lots de fèves prélevés dans le "
                "magasin.", self.display_name))
        lots = lines.mapped('bean_lot_id')
        if len(lots) != len(lines):
            raise UserError(_(
                "Lot d'usinage %s : un même lot de fèves figure sur plusieurs "
                "lignes.", self.display_name))
        lines._check_line()
        certifications = set(lots.mapped(
            lambda l: l.certification_id.id if l.traceability == 'certified' else False))
        if len(certifications) > 1:
            raise UserError(_(
                "Lot d'usinage %s : un lot export ne mélange pas des fèves de "
                "certifications différentes (ni certifiées et ordinaires).",
                self.display_name))
        cocoa_cert = lots[:1].certification_id \
            if lots[:1].traceability == 'certified' else lots.browse()
        expected = self.env['potting.certification'].sudo().search(
            [('cocoa_certification_id', '=', cocoa_cert.id)], limit=1) \
            if cocoa_cert else self.env['potting.certification']
        if cocoa_cert and not expected:
            raise UserError(_(
                "La certification fèves « %s » n'est rattachée à aucune "
                "certification export (Configuration ▸ Certifications : champ "
                "« Certification fèves »).", cocoa_cert.name))
        if self.certification_id != expected:
            if self.certification_id:
                raise UserError(_(
                    "Lot d'usinage %(batch)s : il porte « %(cert)s », les fèves "
                    "prélevées sont « %(lots)s ».", batch=self.display_name,
                    cert=self.certification_id.name,
                    lots=expected.name or _("conventionnelles")))
            self.certification_id = expected
        # Planteurs et parcelles des lots prélevés : source EUDR
        self.source_bean_lot_ids = [(6, 0, lots.ids)]
        if not self.site_lot_ref:
            self.site_lot_ref = self.name

    def _consume_stock_lines(self):
        self.ensure_one()
        for line in self.stock_line_ids:
            # sudo : en mode « par tonnage », seuls le Manager fèves et les
            # chemins système créent des consommations ; celle-ci est un
            # chemin système (sortie d'export pesée), tracé sur le lot.
            consumption = line.bean_lot_id.sudo().consume(
                line.quantity_t,
                notes=_("Sortie export — lot d'usinage %s", self.name),
                export_batch_id=self.id,
                consumption_date=fields.Datetime.now(),
            )
            line.consumption_id = consumption

    # ------------------------------------------------------------------
    # Annulation : le stock revient
    # ------------------------------------------------------------------
    def action_cancel(self):
        warehouse = self.filtered(lambda b: b.origin == 'warehouse')
        result = super().action_cancel()
        warehouse._release_stock()
        return result

    def action_draft(self):
        warehouse = self.filtered(lambda b: b.origin == 'warehouse' and b.state == 'confirmed')
        result = super().action_draft()
        warehouse._release_stock()
        return result

    def _release_stock(self):
        consumptions = self.stock_line_ids.mapped('consumption_id').filtered(
            lambda c: c.state == 'confirmed')
        if consumptions:
            # sudo : l'annulation d'une consommation confirmée est réservée
            # au Manager fèves ; elle est ici la conséquence directe de
            # l'annulation du lot d'usinage (déjà gardée : aucun lot export).
            consumptions.sudo().action_cancel()
        self.stock_line_ids.write({'consumption_id': False})

    def unlink(self):
        if self.stock_line_ids.mapped('consumption_id').filtered(
                lambda c: c.state == 'confirmed'):
            raise UserError(_("Annulez le lot d'usinage avant de le supprimer."))
        return super().unlink()


class CocoaBeanExportBatchStockLine(models.Model):
    _name = 'cocoa.bean.export.batch.stock.line'
    _description = "Lot de fèves prélevé pour l'export"
    _check_company_auto = True

    batch_id = fields.Many2one(
        'cocoa.bean.export.batch', string="Lot d'usinage", required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(related='batch_id.company_id', store=True)
    batch_state = fields.Selection(related='batch_id.state')
    bean_lot_id = fields.Many2one(
        'cocoa.bean.lot', string="Lot de fèves", required=True, index=True,
        ondelete='restrict', check_company=True,
        domain="[('company_id', '=', company_id), "
               "('warehouse_id', '=', parent.warehouse_id), "
               "('state', 'in', ('available', 'partial')), "
               "('cocoa_kind', '=', 'export')]")
    available_t = fields.Float(
        string="Disponible (T)", digits='Cocoa Tonnage',
        related='bean_lot_id.available_quantity')
    free_t = fields.Float(
        string="Libre (T)", digits='Cocoa Tonnage', compute='_compute_free_t',
        help="Disponible moins ce que réservent les ordres de production et "
             "les autres sorties export en brouillon.")
    traceability = fields.Selection(related='bean_lot_id.traceability')
    certification_id = fields.Many2one(related='bean_lot_id.certification_id')
    quantity_t = fields.Float(
        string="Quantité prélevée (T)", digits='Cocoa Tonnage', required=True)
    consumption_id = fields.Many2one(
        'cocoa.bean.consumption', string="Consommation", readonly=True,
        copy=False, ondelete='restrict',
        groups='cocoa_bean_management.group_cocoa_bean_user')

    @api.depends('bean_lot_id', 'bean_lot_id.available_quantity')
    def _compute_free_t(self):
        for line in self:
            lot = line.bean_lot_id
            if not lot:
                line.free_t = 0.0
                continue
            batch = line.batch_id._origin or line.batch_id
            reserved = lot.sudo()._pool_reserved_t(exclude=batch).get(lot.id, 0.0)
            line.free_t = max(lot.available_quantity - reserved, 0.0)

    @api.onchange('bean_lot_id')
    def _onchange_bean_lot_id(self):
        if self.bean_lot_id and not self.quantity_t:
            self.quantity_t = self.free_t

    @api.constrains('quantity_t')
    def _check_quantity_positive(self):
        for line in self:
            if float_compare(line.quantity_t, 0.0, precision_digits=_T_PRECISION) <= 0:
                raise ValidationError(_(
                    "Lot de fèves %s : la quantité prélevée doit être positive.",
                    line.bean_lot_id.name))

    def write(self, vals):
        # La consommation se rattache (et se détache) à la confirmation et à
        # l'annulation : seul ce lien change hors brouillon.
        if set(vals) - {'consumption_id'} and self.filtered(
                lambda l: l.batch_id.state != 'draft'):
            raise UserError(_("Les prélèvements ne changent qu'en brouillon."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda l: l.batch_id.state == 'confirmed'):
            raise UserError(_("Les prélèvements ne changent qu'en brouillon."))
        return super().unlink()

    def _check_line(self):
        """Contrôles de la confirmation, sur des quantités relues sous verrou."""
        self.mapped('bean_lot_id')._lock_for_consumption()
        for line in self:
            lot = line.bean_lot_id
            batch = line.batch_id
            if lot.cocoa_kind != 'export':
                raise UserError(_(
                    "Le lot %s est du cacao brousse : il s'usine avant d'être "
                    "exporté.", lot.name))
            if lot.warehouse_id != batch.warehouse_id:
                raise UserError(_(
                    "Le lot %(lot)s est au magasin %(wh)s, pas à %(batch_wh)s.",
                    lot=lot.name, wh=lot.warehouse_id.name,
                    batch_wh=batch.warehouse_id.name))
            if lot.state not in ('available', 'partial'):
                raise UserError(_("Le lot %s n'est pas disponible.", lot.name))
            reserved = lot.sudo()._pool_reserved_t(exclude=batch).get(lot.id, 0.0)
            free = float_round(lot.available_quantity - reserved,
                               precision_digits=_T_PRECISION)
            if float_compare(line.quantity_t, free, precision_digits=_T_PRECISION) > 0:
                raise UserError(_(
                    "Lot %(lot)s : %(qty).3f T demandées, %(free).3f T libres "
                    "(%(avail).3f T disponibles dont %(res).3f T réservées par "
                    "des ordres de production ou d'autres sorties export).",
                    lot=lot.name, qty=line.quantity_t, free=max(free, 0.0),
                    avail=lot.available_quantity, res=reserved))


class CocoaBeanConsumptionExport(models.Model):
    _inherit = 'cocoa.bean.consumption'

    export_batch_id = fields.Many2one(
        'cocoa.bean.export.batch', string="Sortie export", readonly=True,
        index=True, ondelete='restrict',
        help="Lot d'usinage (sortie du magasin) qui a prélevé ces fèves.")


class CocoaBeanLotExportReservation(models.Model):
    _inherit = 'cocoa.bean.lot'

    def _pool_reserved_t(self, exclude=None):
        """Les sorties export en brouillon réservent leurs fèves : ni
        l'engagement par tonnage ni un ordre de production ne les prend."""
        reserved = dict(super()._pool_reserved_t(exclude=exclude))
        domain = [('batch_id.state', '=', 'draft'),
                  ('batch_id.origin', '=', 'warehouse')]
        if self.ids:
            domain.append(('bean_lot_id', 'in', self.ids))
        if exclude is not None and getattr(exclude, '_name', None) == 'cocoa.bean.export.batch' \
                and exclude.ids:
            domain.append(('batch_id', 'not in', exclude.ids))
        groups = self.env['cocoa.bean.export.batch.stock.line'].sudo()._read_group(
            domain, ['bean_lot_id'], ['quantity_t:sum'])
        for lot, quantity in groups:
            reserved[lot.id] = reserved.get(lot.id, 0.0) + (quantity or 0.0)
        return reserved
