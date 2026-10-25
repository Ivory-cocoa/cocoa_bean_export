# -*- coding: utf-8 -*-
"""Qualité d'un lot d'usinage : évaluée avec les référentiels du projet.

Aucune limite n'est écrite ici. Les mesures du lot sont confrontées :
  * à la NORME D'ACCEPTATION du type de fèves (cocoa.quality.standard du
    module fèves : une norme par certification, sinon celle des fèves
    ordinaires) → conforme / non conforme ;
  * à la GRILLE DES GRADES de la campagne fèves (cocoa.quality.criterion :
    seuils Grade 1 / Grade 2 par critère) → Grade 1, Grade 2, sous-grade.

Les deux référentiels se modifient dans Configuration ▸ Qualité des fèves.
La sévérité du contrôle à la constitution d'un lot export est un réglage
(désactivé / avertissement / blocage) : tant que les normes de la société
ne sont pas arrêtées, l'avertissement informe sans bloquer.
"""

from markupsafe import Markup, escape

from odoo import _, api, fields, models

from odoo.addons.cocoa_bean_management.models.cocoa_campaign import CCC_GRADES

PARAM_QUALITY_CONTROL = 'cocoa_bean_export.quality_control'
QUALITY_CONTROL_MODES = ('off', 'warn', 'block')
DEFAULT_QUALITY_CONTROL = 'warn'

# Critère du laboratoire (cocoa_bean_management.CRITERIA) → champ du lot
QUALITY_FIELDS = {
    'humidity': 'moisture_pct',
    'bean_count': 'bean_count',
    'foreign_matter': 'foreign_matter_pct',
    'broken': 'broken_pct',
    'waste': 'waste_pct',
    'moldy': 'mouldy_pct',
    'slaty': 'slaty_pct',
    'insect': 'insect_damaged_pct',
    'germinated': 'germinated_pct',
    'flat': 'flat_pct',
}
# Mesures pour lesquelles 0 signifie « non mesuré » (une humidité ou un
# grainage nuls n'existent pas) ; ailleurs 0 % de défaut est une mesure.
ZERO_MEANS_UNMEASURED = ('humidity', 'bean_count')

# Rang des grades : CV (GF/F/SS/Limite) et laboratoire (G1/G2/SG)
CV_GRADE_RANK = {'GF': 1, 'F': 2, 'SS': 3, 'LIMIT': 3}
LAB_GRADE_RANK = {'g1': 1, 'g2': 2, 'sg': 3}
DECLARED_GRADE_RANK = CV_GRADE_RANK


class CocoaBeanExportBatchQuality(models.Model):
    _inherit = 'cocoa.bean.export.batch'

    foreign_matter_pct = fields.Float(string="Matières étrangères (%)", digits=(5, 2))
    broken_pct = fields.Float(string="Brisures (%)", digits=(5, 2))
    waste_pct = fields.Float(string="Déchets (%)", digits=(5, 2))
    germinated_pct = fields.Float(string="Germées (%)", digits=(5, 2))
    flat_pct = fields.Float(string="Plates (%)", digits=(5, 2))

    quality_standard_id = fields.Many2one(
        'cocoa.quality.standard', string="Norme appliquée",
        compute='_compute_quality', store=True,
        help="Norme d'acceptation de la certification du lot, sinon celle "
             "des fèves ordinaires (Configuration ▸ Qualité des fèves).")
    quality_grade = fields.Selection(
        CCC_GRADES, string="Grade (grille)", compute='_compute_quality', store=True,
        help="Grade déduit des mesures et de la grille de la campagne fèves.")
    quality_status = fields.Selection([
        ('not_evaluated', "Non évalué"),
        ('conform', "Conforme"),
        ('non_conform', "Non conforme"),
    ], string="Conformité", compute='_compute_quality', store=True, index=True)
    quality_messages = fields.Text(
        string="Constat qualité", compute='_compute_quality', store=True)
    quality_failures = fields.Text(
        string="Critères hors norme", compute='_compute_quality', store=True,
        help="Seulement les mesures hors limite (sans les notes d'information).")

    def _quality_values(self):
        """{critère: valeur} des mesures saisies (non mesuré = absent)."""
        self.ensure_one()
        values = {}
        for criterion, field_name in QUALITY_FIELDS.items():
            value = self[field_name]
            if criterion in ZERO_MEANS_UNMEASURED and not value:
                continue
            values[criterion] = float(value or 0.0)
        return values

    def _has_quality_data(self):
        self.ensure_one()
        return any(self[name] for name in QUALITY_FIELDS.values())

    def _quality_campaign(self):
        """Campagne fèves (grille des grades) couvrant la date de pesée."""
        self.ensure_one()
        return self.env['cocoa.campaign'].sudo()._get_for_date(
            self.date or fields.Date.context_today(self), self.company_id)

    @api.depends(*QUALITY_FIELDS.values(), 'certification_id', 'date', 'company_id')
    def _compute_quality(self):
        Standard = self.env['cocoa.quality.standard'].sudo()
        for batch in self:
            cocoa_cert = batch.certification_id.sudo().cocoa_certification_id
            standard = Standard._for_certification(cocoa_cert)
            batch.quality_standard_id = standard
            if not batch._has_quality_data():
                batch.quality_grade = False
                batch.quality_status = 'not_evaluated'
                batch.quality_messages = _("Aucune mesure de qualité saisie.")
                batch.quality_failures = False
                continue
            values = batch._quality_values()
            messages, failures = [], []
            conform = True
            if standard:
                conform, failures = standard._evaluate(values)
                messages += failures
            else:
                messages.append(_("Aucune norme d'acceptation configurée : "
                                  "conformité non contrôlée."))
            campaign = batch._quality_campaign()
            grade = False
            if campaign:
                grade, reject, grade_messages = campaign._evaluate_quality(values)
                messages += grade_messages
                if reject:
                    failures += [m for m in grade_messages if m not in failures]
                conform = conform and not reject
            else:
                messages.append(_("Aucune campagne fèves à cette date : grade "
                                  "non calculé."))
            batch.quality_grade = grade
            batch.quality_status = 'conform' if conform else 'non_conform'
            batch.quality_messages = "\n".join(messages) or _("Conforme à la norme.")
            batch.quality_failures = "\n".join(failures) or False

    def action_evaluate_quality(self):
        """Réévalue après un changement de norme ou de grille."""
        self._compute_quality()
        return True

    # ------------------------------------------------------------------
    # Contrôle à la constitution d'un lot export
    # ------------------------------------------------------------------
    @api.model
    def _quality_control_mode(self):
        mode = self.env['ir.config_parameter'].sudo().get_param(PARAM_QUALITY_CONTROL)
        return mode if mode in QUALITY_CONTROL_MODES else DEFAULT_QUALITY_CONTROL

    def _quality_issues_for_lot(self, lot):
        """Constats qui s'opposent à l'affectation de ce lot d'usinage à
        ``lot`` : non-conformité à la norme, grade inférieur à celui de la
        CV de l'OT."""
        self.ensure_one()
        issues = []
        if self.quality_status == 'non_conform':
            issues.append(_("%(batch)s non conforme à la norme %(std)s : %(why)s",
                            batch=self.name,
                            std=self.quality_standard_id.name or '',
                            why=(self.quality_failures or '').replace('\n', ' ; ')))
        cv = lot.transit_order_id.confirmation_vente_id
        required = CV_GRADE_RANK.get(cv.grade_qualite) if cv else None
        actual = (LAB_GRADE_RANK.get(self.quality_grade)
                  or DECLARED_GRADE_RANK.get(self.grade))
        if required and actual and actual > required:
            issues.append(_(
                "%(batch)s : grade %(actual)s inférieur au grade de la CV "
                "%(cv)s (%(required)s).",
                batch=self.name,
                actual=(dict(CCC_GRADES).get(self.quality_grade)
                        or dict(self._fields['grade'].selection).get(self.grade)),
                cv=cv.display_name,
                required=dict(cv._fields['grade_qualite'].selection).get(cv.grade_qualite)))
        return issues

    @api.model
    def _quality_issues_html(self, issues):
        return Markup("<ul>%s</ul>") % Markup().join(
            Markup("<li>%s</li>") % escape(issue) for issue in issues)
