# Exportation des fèves de cacao (`cocoa_bean_export`)

Export de fèves de cacao brutes (SH 1801 00 00 00) sur le socle **Gestion des
Exportations** (`potting_management`) : contrats, CV, formules FO1, OT, lots,
conteneurs, BL, D6, factures, soutien/reversement et tableaux de bord sont
ceux du socle. Ce module n'ajoute que ce qui est propre aux fèves.

## Circuit

1. **Lot d'usinage** (Production ▸ Lots d'usinage) : saisie du bulletin de
   pesée de sortie du site — n° de lot du site, n° de bulletin, sacs, poids
   brut, tare (net = brut − tare), mesures qualité, certification. Confirmer.
2. **OT de fèves** → générer les lots (découpage au tonnage maximal réglé).
3. **Constituer le lot** (bouton du lot export) : affecter des sacs de lots
   d'usinage. Le tonnage est le **poids net pesé** au prorata des sacs ; les
   derniers sacs d'un lot d'usinage en prennent le reste exact. « Lot
   complet » ramène la cible au poids réel et passe le lot prêt pour
   empotage.
4. Empotage, BL, D6, facture : socle (code SH, nature « FÈVES DE CACAO »,
   colis = sacs, coefficient de conversion de la formule = 1).

## Réglages (Paramètres ▸ Gestion des Empotages ▸ Export des fèves)

| Réglage | Défaut |
|---|---|
| Exporter aussi des semi-finis | non (fèves uniquement : semi-finis masqués et refusés, menus d'usine cachés) |
| Conditionnement | sacs de jute (poids nominal 65 kg, tare 1 kg) ou vrac (unité = kg, tare 0) |
| Tonnage maximal d'un lot | 25 T |
| Préfixe des lots | F |
| Contrôle qualité | avertissement (désactivé / avertissement / blocage avec dérogation motivée d'un Manager) |

Identité imprimée (nom commercial, sigle, NCC, REX, ID RA) : bloc
« Identité de la société » des mêmes Réglages.

## Qualité

Aucune limite n'est codée ici : les mesures du lot d'usinage sont évaluées
avec les référentiels du module fèves, modifiables dans Configuration ▸
Qualité des fèves :

- **Normes d'acceptation** (une par certification, sinon fèves ordinaires) →
  conforme / non conforme ;
- **Grilles des grades** (par campagne fèves) → Grade 1 / Grade 2 /
  sous-grade, comparé au grade de la CV de l'OT.

## Documents d'export (BL)

Chaque BL de fèves reçoit une ligne par type de document actif
(Configuration ▸ Documents d'export des fèves). Valeurs de départ, à ajuster :

| Document | Exigence | Pièce jointe |
|---|---|---|
| Certificat phytosanitaire | à la confirmation de la facture | oui |
| Certificat de fumigation | à la confirmation de la facture | oui |
| Certificat d'origine | à la confirmation de la facture | oui |
| Certificat de qualité (CCC) | à la confirmation de la facture | oui |
| Certificat de poids | facultatif | non |
| Certificat de transaction | facultatif, lots certifiés seulement | non |

Un type peut aussi être limité aux destinations UE et porter une **validité**
(jours avant l'embarquement, ex. fumigation). Le contrôle porte sur
l'écriture de l'état (BL confirmé, facture confirmée) : confirmation
unitaire ou groupée, même porte.

## EUDR

Par lot d'usinage, deux sources : les **lots de fèves d'origine** suivis dans
Odoo (éligibilité du module fèves), ou un **GeoJSON fourni** par le site ou
les coopératives, contrôlé à l'import (FeatureCollection, Point / Polygon /
MultiPolygon, coordonnées [longitude, latitude] en Côte d'Ivoire, polygones
fermés) puis **vérifié par un Manager**. Le lot export et le BL en héritent ;
le dossier EUDR du BL (socle) inclut les parcelles fournies.

## Réclamations à l'arrivée

Expédition ▸ Réclamations à l'arrivée (ou bouton du BL), une seule en cours
par BL. Perte = net embarqué − net débarqué ; au-delà de la franchise
(0,5 % par défaut, réglable) elle est valorisée au prix au kg de la facture ;
s'y ajoute un montant qualité (expertise, arbitrage). Cycle : brouillon →
présentée → accordée (Manager, jamais au-delà du réclamé) → réglée par un
avoir (assistant du socle, pré-rempli) ou par une pièce comptable externe.

## Import de l'historique

Production ▸ Importer des lots d'usinage : classeur .xlsx dont les colonnes
sont reconnues par leur en-tête (alias, ordre libre ; obligatoires : n° de
lot du site, site, date, poids brut). « Analyser » contrôle sans rien créer
(site, certification, poids, doublons dans le fichier et en base) ;
« Importer » crée les lignes valides, en brouillon ou confirmées. Modèle
téléchargeable. Les contrats, CV, formules et OT s'importent avec les
assistants du socle (« Fèves » reconnu).

## Guide utilisateur

Aide ▸ Guide Export des fèves (`/aide/beans`, FR/EN, PDF) : chapitres
filtrés par profil.

## Mode « fèves uniquement »

Semi-finis retirés des listes de choix, refusés à l'enregistrement, cartes
du tableau de bord et menus d'usine masqués, filtres de recherche « Masse /
Beurre / Cake / Poudre » cachés (groupe technique accordé ou retiré selon le
réglage).

## Tests

`--test-tags /cocoa_bean_export` (40 tests). Les tests de `potting_management` se
lancent sur une base **sans** ce module (le mode fèves uniquement y refuse
les semi-finis).
