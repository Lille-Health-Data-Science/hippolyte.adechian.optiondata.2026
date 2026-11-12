# Séance 1 · FHIR — d'un export FHIR à un mini-entrepôt OMOP

Projet réalisé dans le cadre du Master 2 Data Science en Santé (Université de Lille), séance 1 « FHIR, échanger les données de santé ».
Il montre comment passer d'un export FHIR (NDJSON) à des tables OMOP (`PERSON`, `MEASUREMENT`) avec DuckDB, en harmonisant les unités des glycémies, puis comment répondre à une question clinique à partir de ces tables.


## Ce que fait le notebook

| Partie | Contenu |
|---|---|
| **A** | Écrire et valider une ressource `Observation` (`fhir.resources`), exécuter une recherche FHIR, extraire des valeurs avec FHIRPath |
| **B** | Interroger le serveur public HAPI (métadonnées, recherche, transaction, pagination) |
| **C** | Construire `PERSON` et `MEASUREMENT` à partir de l'export, avec DuckDB, puis appliquer un critère clinique |
| **D** | Explorer : seuil du critère, courbe d'un patient, HbA1c, effet de la conversion d'unités |

### Le pipeline du TP 2

1. **Explorer** l'export : trois laboratoires, trois unités (mg/dL, g/L, mmol/L), des HbA1c et des mesures `cancelled` ou `entered-in-error`.
2. **Harmoniser** dans `stg_glycemie` : on garde les statuts `final`, les LOINC 2345-7 et 14749-6 et les valeurs positives, puis on convertit en mg/dL (g/L × 100 ; mmol/L × 18,016) en gardant la valeur, l'unité et le code d'origine.
3. **Mapper** vers OMOP : `person` (concepts de genre 8507 et 8532) et `measurement` (concept 3004501, unité 8840, type 32817).
4. **Interroger** : au moins 2 glycémies ≥ 126 mg/dL, croisées avec les diagnostics (SNOMED 44054006).

## Résultats principaux

| Questions | Réponses |
|---|---|
| Glycémies exploitables après nettoyage | 835 |
| Patients avec ≥ 2 glycémies ≥ 126 mg/dL | 59, dont 9 sans diagnostic codé |
| Même critère avec un seuil à 110 mg/dL | 70 patients, dont 17 sans diagnostic |
| Glycémies ≥ 126 mg/dL qui auraient échappé sans conversion | 41,2 % (119 sur 289) |
| Patients avec HbA1c ≥ 6,5 % | 53, aucun sans diagnostic codé |
| Patient à la glycémie maximale | p-0071 (254 mg/dL) |