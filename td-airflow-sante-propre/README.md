# TD Airflow

## Résumé

| Partie | Objectif | Résultat |
|---|---|---|
| Installation | Airflow en Docker, DAG `verification_installation` | 7 services `healthy`, exécution `success` |
| 01 · Premier DAG | Ajouter la tâche `controler` | `controler` échoue si n < 100, `charger` passe en `upstream_failed` |
| 02 · Prévoir les exécutions | Compter les exécutions de `prevoir_executions` | 12 exécutions planifiées, première `logical_date` 2026-11-01 06:00 UTC |
| 04 · Flux FHIR quotidien | DAG `fhir_glycemies_quotidien` en 4 tâches | Les 4 tâches passent au vert |

## Partie 01 · Premier DAG

**Consigne :** ajouter une tâche `controler` entre `transformer` et `charger`, qui lève `ValueError` si n < 100. Que voit-on dans Grid avec `nb_patients = 40` ?

```python
@task
def controler(n: int) -> int:
    if n < 100:
        raise ValueError(f"Trop peu de lignes : {n} < 100")
    print(f"Contrôle OK : {n} lignes")
    return n

charger(controler(transformer(extraire())))
```

Avec `nb_patients = 40`, `transformer` renvoie 80 et `controler` échoue :

| Tâche | État | Couleur |
|---|---|---|
| `extraire` | `success` | vert |
| `transformer` | `success` | vert |
| `controler` | `failed` (`ValueError: Trop peu de lignes : 80 < 100`) | rouge |
| `charger` | `upstream_failed` (non exécutée) | orange |

L'exécution entière est en échec. Le contrôle empêche de charger des données incomplètes. Avec `nb_patients = 150` (n = 300), les quatre tâches sont vertes et `charger` affiche « Chargement de 300 lignes ».

**Captures de la vue Grid** (une colonne par exécution, de la plus ancienne à gauche à la plus récente à droite) :

1. **Après l'ajout de `controler`, avec `nb_patients = 150` :** les deux premières exécutions n'ont pas de ligne `controler` (la tâche n'existait pas encore) ; la dernière, avec `controler`, est entièrement verte.

   ![Grid de mon_premier_dag : controler et charger verts](<captures/Capture d'écran 2026-11-12 155522.png>)

2. **Avec `nb_patients = 40` :** `controler` est rouge (✗, `ValueError`), `charger` est orange (`upstream_failed`), et l'exécution entière est en échec. `extraire` et `transformer` restent verts.

   ![Grid de mon_premier_dag : controler en échec, charger upstream_failed](<captures/Capture d'écran 2026-11-12 155910.png>)

## Partie 02 · Prévoir les exécutions

DAG `prevoir_executions` : `schedule="0 6 * * *"`, `start_date=datetime(2026, 11, 1)`, `catchup=True`.

**Prévision.** Il y a une exécution par jour à 6 h UTC. Le TD a été refait le 12 novembre 2026 à 21 h 45 UTC, donc le 6 h du 12 novembre était déjà passé :
- **12 exécutions** (du 1er au 12 novembre) ;
- première `logical_date` : **2026-11-01 06:00 UTC** (7 h à Paris).

**Constat.** `airflow dags list-runs prevoir_executions` affiche bien 12 exécutions `scheduled__...` en `success` (du 1er au 12 novembre, à 06:00 UTC), plus une exécution manuelle. Pour chaque ligne, `run_after` est égal à `logical_date` : Airflow 3 déclenche l'exécution à l'heure du cron (`CronTriggerTimetable`) et non à la fin d'un intervalle de données. Les 12 exécutions ont été rattrapées en parallèle au moment de l'activation.

**Capture de la sortie de `airflow dags list-runs prevoir_executions`** : 13 lignes, soit les 12 exécutions `scheduled__` du 1er au 12 novembre (toutes en `success`, `run_after` égal à `logical_date`) et l'exécution `manual__` du 12 novembre.

![Sortie de list-runs pour prevoir_executions : 12 exécutions planifiées et une manuelle](<captures/Capture d'écran 2026-11-13 153432.png>)

**Avec `catchup=False` et `dag_id="prevoir_executions_v2"` :** l'activation crée **une seule** exécution planifiée, la plus récente : `scheduled__2026-11-12T06:00:00+00:00`.

## Partie 04 · Le flux FHIR quotidien

Le DAG `fhir_glycemies_quotidien` enchaîne quatre tâches :

```
extraire (API FHIR) → aplatir (Parquet) → valider (Pandera) → charger (DuckDB)
```

| Étape | Tâche | Ce qu'elle fait |
|---|---|---|
| 1 | `extraire` | Lit les glycémies (LOINC 2345-7) par pagination FHIR (lien `next`, `raise_for_status()` pour déclencher les retries), ou copie le fichier d'exemple si `source = fichier` |
| 2 | `aplatir` | Une ligne par Observation (`id`, `patient`, `date`, `statut`, `valeur`, `unite`), écrite en Parquet |
| 3 | `valider` | Schéma Pandera : patient non nul, valeur > 0 non nulle, unité dans `g/L`, `mg/dL`, `mmol/L` ; les lignes invalides sont écartées et comptées |
| 4 | `charger` | `DELETE` des lignes du jour puis `INSERT` depuis `read_parquet`, valeur convertie en mg/dL (g/L × 100, mmol/L × 18,016) : rejouable sans doublon |

Choix de conception :
- **XCom léger :** chaque tâche renvoie un chemin de fichier, pas les données.
- **Idempotence :** la suppression des lignes du jour avant l'insertion évite les doublons à chaque relance.
- **Fiabilité :** `extraire` a 3 retries à 20 secondes d'écart (en production : 5 retries à 2 minutes), et `on_failure_callback` écrit l'alerte dans `donnees/alertes.log`.
- **Pool `api_fhir` (3 places) :** limite les appels simultanés au serveur FHIR.

Résultat : les **quatre tâches sont vertes** dans Grid. La capture ci-dessous montre trois exécutions, de gauche à droite :

1. **l'exécution planifiée créée à l'activation, avant l'étape 1 :** `extraire` est rouge (« Étape 1 à compléter », après ses trois retries) et les tâches suivantes sont orange (`upstream_failed`) ;
2. **le premier lancement avec `source = fichier` :** `extraire` est vert, `aplatir` est rouge (« Étape 2 à compléter ») et `valider` et `charger` sont orange ;
3. **le lancement avec le DAG complété :** les quatre tâches sont vertes.

![Grid de fhir_glycemies_quotidien : de l'échec au succès](<captures/Capture d'écran 2026-11-13 001401.png>)

Vérifications du TD (4.4) :
- **Aucun doublon :** relancer avec la même source ne change pas le total affiché par `charger`.
- **Panne :** avec une mauvaise adresse (`https://hapi.fhir.org/baseR5x`) et `source = api`, `extraire` passe trois fois en `up_for_retry` à 20 secondes d'écart, puis en échec, et une ligne d'alerte s'ajoute à `donnees/alertes.log`.
