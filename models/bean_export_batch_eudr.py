# -*- coding: utf-8 -*-
"""EUDR des fèves exportées : du lot d'usinage au dossier du BL.

Deux sources de traçabilité, au choix par lot d'usinage :
  * les LOTS DE FÈVES d'origine suivis dans Odoo (module fèves : planteurs,
    parcelles géolocalisées, contrôles) — l'éligibilité est alors celle des
    lots, calculée par le module fèves ;
  * un fichier GEOJSON fourni par le site d'usinage ou les coopératives,
    tant que l'amont n'est pas suivi dans Odoo. Le fichier est contrôlé à
    l'import (structure, coordonnées en Côte d'Ivoire, polygones fermés) puis
    vérifié par un Manager : avant cette vérification, le lot reste « à
    compléter / vérifier ».

Le lot export de fèves reprend l'état de ses lots d'usinage, le BL celui de
ses lots ; le dossier EUDR du BL (socle) y ajoute les entités des fichiers
fournis.
"""

import base64
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.potting_management.models.potting_eudr import EUDR_STATES, _aggregate

# Côte d'Ivoire, avec une marge : une coordonnée hors de ce cadre est une
# erreur de saisie (inversion latitude/longitude, signe oublié…).
CI_BOUNDS = {'lat': (4.0, 11.0), 'lon': (-9.0, -2.0)}
GEOMETRY_TYPES = ('Point', 'Polygon', 'MultiPolygon')


def _check_position(position, where):
    if (not isinstance(position, (list, tuple)) or len(position) < 2
            or not all(isinstance(v, (int, float)) for v in position[:2])):
        raise ValidationError(_("%s : coordonnée invalide %s.", where, position))
    lon, lat = position[0], position[1]
    if not (CI_BOUNDS['lon'][0] <= lon <= CI_BOUNDS['lon'][1]
            and CI_BOUNDS['lat'][0] <= lat <= CI_BOUNDS['lat'][1]):
        raise ValidationError(_(
            "%(where)s : le point (longitude %(lon)s, latitude %(lat)s) est hors "
            "de Côte d'Ivoire. Vérifiez l'ordre [longitude, latitude] du GeoJSON.",
            where=where, lon=lon, lat=lat))


def _check_ring(ring, where):
    if not isinstance(ring, list) or len(ring) < 4:
        raise ValidationError(_("%s : un polygone a au moins 4 positions.", where))
    for position in ring:
        _check_position(position, where)
    if list(ring[0][:2]) != list(ring[-1][:2]):
        raise ValidationError(_("%s : le polygone n'est pas fermé (premier point "
                                "≠ dernier point).", where))


def parse_geojson(raw):
    """Contrôle un GeoJSON de parcelles ; renvoie la liste des entités."""
    try:
        data = json.loads(raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(_("Fichier GeoJSON illisible : %s", exc)) from None
    if isinstance(data, dict) and data.get('type') == 'Feature':
        data = {'type': 'FeatureCollection', 'features': [data]}
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection' \
            or not isinstance(data.get('features'), list):
        raise ValidationError(_("Le fichier doit être un GeoJSON « FeatureCollection »."))
    features = data['features']
    if not features:
        raise ValidationError(_("Le GeoJSON ne contient aucune parcelle."))
    for index, feature in enumerate(features, start=1):
        where = _("Parcelle n° %s", index)
        geometry = (feature or {}).get('geometry') or {}
        kind, coords = geometry.get('type'), geometry.get('coordinates')
        if kind not in GEOMETRY_TYPES:
            raise ValidationError(_(
                "%(where)s : géométrie « %(kind)s » non admise (Point, Polygon "
                "ou MultiPolygon).", where=where, kind=kind))
        if kind == 'Point':
            _check_position(coords, where)
        elif kind == 'Polygon':
            for ring in coords or [None]:
                _check_ring(ring, where)
        else:
            for polygon in coords or [[None]]:
                for ring in polygon or [None]:
                    _check_ring(ring, where)
    return features


class CocoaBeanExportBatchEudr(models.Model):
    _inherit = 'cocoa.bean.export.batch'

    source_bean_lot_ids = fields.Many2many(
        'cocoa.bean.lot', 'bean_export_batch_source_lot_rel', 'batch_id', 'bean_lot_id',
        string="Lots de fèves d'origine",
        help="Quand l'amont est suivi dans Odoo : lots de fèves usinés dans ce "
             "lot. Leur éligibilité EUDR fait foi.")
    eudr_geojson = fields.Binary(
        string="Géolocalisation fournie (GeoJSON)", attachment=True, copy=False,
        help="Parcelles d'origine fournies par le site ou les coopératives "
             "(FeatureCollection, coordonnées [longitude, latitude]).")
    eudr_geojson_name = fields.Char(string="Nom du fichier", copy=False)
    eudr_feature_count = fields.Integer(
        string="Parcelles fournies", compute='_compute_eudr_features', store=True)
    eudr_supplier_reference = fields.Char(
        string="Référence traçabilité fournisseur", tracking=True,
        help="Référence du dossier de traçabilité remis par le site ou la "
             "coopérative.")
    eudr_verified = fields.Boolean(
        string="Géolocalisation vérifiée", readonly=True, copy=False, tracking=True)
    eudr_verified_by_id = fields.Many2one('res.users', string="Vérifiée par",
                                          readonly=True, copy=False)
    eudr_verified_date = fields.Datetime(string="Vérifiée le", readonly=True, copy=False)
    eudr_state = fields.Selection(EUDR_STATES, string="EUDR",
                                  compute='_compute_eudr', compute_sudo=True)
    eudr_reason = fields.Text(string="Motif EUDR", compute='_compute_eudr',
                              compute_sudo=True)

    @api.depends('eudr_geojson')
    def _compute_eudr_features(self):
        for batch in self:
            count = 0
            if batch.eudr_geojson:
                try:
                    count = len(parse_geojson(base64.b64decode(batch.eudr_geojson)))
                except ValidationError:
                    count = 0
            batch.eudr_feature_count = count

    @api.constrains('eudr_geojson')
    def _check_eudr_geojson(self):
        for batch in self.filtered('eudr_geojson'):
            parse_geojson(base64.b64decode(batch.eudr_geojson))

    def _eudr_source_lots(self):
        """Lots de fèves d'origine suivis dans Odoo (étendu par l'usinage)."""
        self.ensure_one()
        return self.source_bean_lot_ids

    @api.depends('source_bean_lot_ids.eudr_state', 'eudr_geojson', 'eudr_verified',
                 'processing_id.line_ids.lot_id.eudr_state')
    def _compute_eudr(self):
        for batch in self:
            beans = batch._eudr_source_lots()
            if beans:
                batch.eudr_state = _aggregate(set(beans.mapped('eudr_state')))
                batch.eudr_reason = "\n".join(
                    "%s : %s" % (bean.name, (bean.eudr_reason or '').replace('\n', ' '))
                    for bean in beans if bean.eudr_state != 'eligible') or False
            elif batch.eudr_geojson and batch.eudr_verified:
                batch.eudr_state, batch.eudr_reason = 'eligible', False
            elif batch.eudr_geojson:
                batch.eudr_state = 'pending'
                batch.eudr_reason = _("Géolocalisation fournie, à vérifier par "
                                      "un Manager.")
            else:
                batch.eudr_state = 'not_traced'
                batch.eudr_reason = _("Ni lots de fèves d'origine, ni "
                                      "géolocalisation fournie.")

    def write(self, vals):
        # Un nouveau fichier n'a pas été vérifié
        if 'eudr_geojson' in vals and not self.env.context.get('bean_eudr_keep_verified'):
            vals = dict(vals, eudr_verified=False, eudr_verified_by_id=False,
                        eudr_verified_date=False)
        return super().write(vals)

    def action_eudr_verify(self):
        if not self.env.user.has_group('potting_management.group_potting_manager'):
            raise UserError(_("Seul un Manager vérifie une géolocalisation fournie."))
        for batch in self:
            if not batch.eudr_geojson:
                raise UserError(_("Lot d'usinage %s : aucun GeoJSON fourni.", batch.name))
            batch.write({
                'eudr_verified': True,
                'eudr_verified_by_id': self.env.user.id,
                'eudr_verified_date': fields.Datetime.now(),
            })
            batch.message_post(body=_(
                "Géolocalisation vérifiée (%s parcelle(s)).", batch.eudr_feature_count))
        return True

    def action_eudr_unverify(self):
        if not self.env.user.has_group('potting_management.group_potting_manager'):
            raise UserError(_("Seul un Manager retire une vérification."))
        self.write({'eudr_verified': False, 'eudr_verified_by_id': False,
                    'eudr_verified_date': False})
        return True

    def _eudr_supplied_features(self):
        """Entités GeoJSON fournies (lots d'usinage sans lots d'origine)."""
        features = []
        for batch in self.filtered(lambda b: b.eudr_geojson and not b._eudr_source_lots()):
            features += parse_geojson(base64.b64decode(batch.eudr_geojson))
        return features


class PottingLotBeanEudr(models.Model):
    _inherit = 'potting.lot'

    @api.depends('bean_lot_ids', 'bean_consumption_ids.bean_lot_id',
                 'production_line_ids.bean_batch_id.eudr_state',
                 'production_line_ids.bean_batch_id.source_bean_lot_ids',
                 'production_line_ids.bean_batch_id.processing_id')
    def _compute_eudr(self):
        beans_lots = self.filtered(lambda l: l.product_type == 'cocoa_beans')
        super(PottingLotBeanEudr, self - beans_lots)._compute_eudr()
        for lot in beans_lots:
            batches = lot.production_line_ids.mapped('bean_batch_id')
            lot.eudr_bean_lot_ids = self.env['cocoa.bean.lot'].union(
                *[batch._eudr_source_lots() for batch in batches])
            if not batches:
                lot.eudr_state = 'not_traced'
                lot.eudr_reason = _("Lot non constitué : aucun lot d'usinage.")
                continue
            lot.eudr_state = _aggregate(set(batches.mapped('eudr_state')))
            lot.eudr_reason = "\n".join(
                "%s : %s" % (batch.name, (batch.eudr_reason or '').replace('\n', ' '))
                for batch in batches if batch.eudr_state != 'eligible') or False


class PottingDeliveryNoteBeanEudr(models.Model):
    _inherit = 'potting.delivery.note'

    def _eudr_feature_collection(self):
        collection, beans, plots = super()._eudr_feature_collection()
        batches = self.lot_ids.sudo().production_line_ids.mapped('bean_batch_id')
        collection['features'] = collection['features'] + batches._eudr_supplied_features()
        return collection, beans, plots
