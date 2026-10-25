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

## Tests

`--test-tags /cocoa_bean_export`. Les tests de `potting_management` se
lancent sur une base **sans** ce module (le mode fèves uniquement y refuse
les semi-finis).
