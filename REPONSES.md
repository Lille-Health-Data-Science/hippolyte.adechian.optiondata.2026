# Séance 1 · FHIR — Réponses aux questions du notebook

Chiffres obtenus en exécutant `seance1_etudiant_corrige.ipynb` sur `donnees/export_fhir/` (150 patients, 984 observations, 55 conditions).
Les cellules qui interrogent le serveur public HAPI (A2, partie B) n'ont pas pu être exécutées depuis mon environnement (réseau bloqué) : le code est complété, mais les réponses correspondantes sont conceptuelles. À relancer de votre côté.

## A · Partie 01 et 02
**A1 – Validation.** `obs2` : date `2026-09-02T08:10:00+02:00`, valeur 1,26 g/L, et `"encounter": {"reference": "Encounter/sejour-001"}` (élément `Observation.encounter`). `fhir.resources` la valide.
**Deux erreurs, deux comportements.** La date « 02/09/2026 » est **refusée** : `dateTime` suit une expression régulière précise (ISO 8601). Le statut inventé « terminé » est **accepté** : `fhir.resources` vérifie la structure et les formats, pas l'appartenance d'un code à son jeu de valeurs (binding). Un code faux mais bien formé passe donc, d'où l'intérêt de valider aussi les terminologies (serveur de terminologie, profils).
**A2 – Recherche.** `_sort=-date`, `_count=5` ; on s'attend à un Bundle de type `searchset`, 5 entrées maximum ; le patient est `b["entry"][0]["resource"]["subject"]["reference"]`, réutilisé dans `patient=`.
**A3 – FHIRPath.** Prénom : `Patient.name.where(use = 'official').given.first()` → « Marie ». Date : `Observation.effective.ofType(dateTime)` → `2026-09-01T08:30:00+02:00`.
`ofType(Quantity)` ne renvoie rien sans `model` car `value[x]` est un type choix : dans le JSON la clé est `valueQuantity`, et seul le modèle R4 sait que `value` + `Quantity` correspondent à cette clé.

## B · TP 1 (serveur public)
Sur le serveur public, attendez-vous à des unités hétérogènes (mg/dL, g/L, mmol/L, sans unité) et à des valeurs impossibles (zéro, négatives, ou extrêmes de plusieurs ordres de grandeur) : n'importe qui peut y écrire, sans contrôle de qualité. Une valeur numérique sans son unité n'a pas de sens ; il faut harmoniser et filtrer avant toute analyse.

## C · TP 2 (export → OMOP)
**C1 – Exploration.** 984 observations : glycémie mg/dL 463 finales, g/L 193, mmol/L 179 ; HbA1c 117 (%) ; 24 `cancelled` (sans valeur ni unité) et 8 `entered-in-error`. Trois unités pour le même examen, un examen différent (HbA1c) mêlé aux glycémies, et des mesures à écarter.
**C1 bis.** Les valeurs brutes sont sur 3 ordres de grandeur (~1 en g/L, ~6 en mmol/L, ~100 en mg/dL) : une moyenne brute mélangerait des unités et serait dénuée de sens.
**C2 – Harmonisation.** 835 glycémies exploitables. Moyennes après conversion : mg/dL 115,9 ; g/L 115,8 ; mmol/L 114,2 → même ordre de grandeur, la conversion est bonne.
**C3/C4.** PERSON : 150 lignes (8507 homme, 8532 femme). MEASUREMENT : 835 lignes (concept 3004501, unité 8840, type 32817), avec la source conservée dans `*_source_value`.
**C5 – Critère (≥ 2 glycémies ≥ 126 mg/dL).** **59 patients** remplissent le critère ; **9** n'ont **pas** de diagnostic de diabète (SNOMED 44054006) dans `Condition`. (Contre-vérifié avec une requête indépendante. Seuls 5 des 55 patients diagnostiqués ne remplissent pas le critère.)
Remarque : les données n'indiquent pas si la glycémie est à jeun ; on traite donc toutes les glycémies comme telles.
**À discuter.** Sans conversion, le critère « ≥ 126 » ne retiendrait aucune valeur en g/L ou en mmol/L : erreur silencieuse, sans message ni plantage.
**C5 bis.** Les points orange dans la zone sont des patients au critère mais sans diagnostic codé (cas probablement non diagnostiqués ou diagnostic non saisi) ; les points bleus hors zone sont des patients codés diabétiques sans 2 valeurs hautes (diabète équilibré par le traitement, peu de mesures, ou codage erroné).

## D · Explorer
**D1.** Avec un seuil à 110 mg/dL : 70 patients au critère, dont **17 sans diagnostic** (contre 9 à 126). Le seuil arbitre entre sensibilité (ne rater personne) et spécificité (éviter les faux positifs, les examens et l'inquiétude inutiles) : c'est un compromis clinique, qui engage les patients, pas un réglage technique.
**D2.** 9 patients au critère sans diagnostic : p-0100, p-0058, p-0020, p-0019, p-0105, p-0089, p-0132, p-0134, p-0142. Message au médecin traitant : « plusieurs glycémies ≥ 1,26 g/L sans diagnostic codé ; à confirmer (HbA1c, contrôle à jeun) et à coder si confirmé ». Le critère ne fait pas le diagnostic.
**D3 – Défi 1.** 289 glycémies sont ≥ 126 mg/dL ; sans conversion, 170 seraient retenues (toutes en mg/dL) et **119 (41,2 %) échapperaient** : 65 en g/L et 54 en mmol/L.
**Défi 2.** 117 HbA1c (5,1 à 9,5 %), 55 patients dosés ; **53 ont une HbA1c ≥ 6,5 %, dont 0 sans diagnostic codé**. Les 95 patients sans diagnostic n'ont **aucune** HbA1c : on ne dose que les patients déjà identifiés comme diabétiques. Biais de sélection : les non-diagnostiqués restent invisibles pour ce marqueur et l'HbA1c ne peut pas servir à les repérer dans ces données.
**Défi 3.** Patient **p-0071**, glycémie maximale 254 mg/dL (2,54 g/L, le 23/11/2025) ; sa courbe est tracée par `courbe("p-0071")`.

## Pour aller plus loin
Garder les mmol/L avec leur concept d'origine (3013826) respecte mieux la source mais complique l'analyse (il faudrait convertir à chaque requête) ; harmoniser en mg/dL (3004501) facilite l'analyse, à condition de conserver valeur, unité et code d'origine pour la traçabilité, comme fait ici.
