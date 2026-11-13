"""TP séance 2 · Cas d'usage : le flux FHIR quotidien des glycémies.

extraire (API FHIR, pagination) → aplatir (Parquet) → valider (Pandera) → charger (DuckDB, idempotent)
Le guide pas à pas est dans TD.md (partie 04).

Avant de commencer :
  - copier ce fichier dans dags/ ;
  - créer le pool api_fhir : Admin › Pools › + , nom api_fhir, 3 places.
Sans réseau : déclencher avec le paramètre source = fichier (formulaire « Trigger »).
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow.sdk import Asset, Param, dag, task
from airflow.timetables.trigger import CronTriggerTimetable

DONNEES = Path(__file__).resolve().parents[1] / "donnees"
BASE = os.environ.get("FHIR_BASE", "https://hapi.fhir.org/baseR4")   # panne volontaire (TD.md, 4.4) : mettre une mauvaise URL
UNITES = ["g/L", "mg/dL", "mmol/L"]
EXEMPLE = DONNEES / "exemple" / "glycemies_exemple.ndjson"     # repli sans réseau (données de la séance 1)
glycemies = Asset("glycemies")


def jour(data_interval_start) -> str:
    """Le jour traité ; une exécution manuelle n'a pas d'intervalle : on prend la veille."""
    return (data_interval_start or datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def alerter(context):
    """Appelée quand une tâche échoue définitivement (après ses retries)."""
    ti = context["ti"]
    message = f"ALERTE {datetime.now():%H:%M:%S} · {ti.dag_id}.{ti.task_id} en échec : {context.get('exception')}"
    print(message)
    with open(DONNEES / "alertes.log", "a") as f:
        f.write(message + "\n")


@dag(schedule=CronTriggerTimetable("0 6 * * *", timezone="Europe/Paris", interval=timedelta(days=1)),
     start_date=datetime(2026, 11, 1), catchup=False, tags=["fhir", "tp"],
     default_args={"on_failure_callback": alerter},
     params={"source": Param("api", enum=["api", "fichier"],
                             description="api : serveur FHIR public ; fichier : données d'exemple, sans réseau")})
def fhir_glycemies_quotidien():

    # En production : retries=5, retry_delay=2 min ; raccourci ici pour voir la panne pendant le TP
    @task(pool="api_fhir", retries=3, retry_delay=timedelta(seconds=20))
    def extraire(params=None, data_interval_start=None) -> str:
        """Étape 1 : glycémies (LOINC 2345-7) modifiées depuis le début de l'intervalle, toutes pages."""
        import requests

        chemin = DONNEES / "brut" / f"glycemies_{jour(data_interval_start)}.ndjson"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if params["source"] == "fichier":
            chemin.write_text(EXEMPLE.read_text())
            print("Source fichier :", EXEMPLE)
            return str(chemin)

        url = f"{BASE}/Observation"
        requete = {"code": "http://loinc.org|2345-7", "_count": 100,
                   "_lastUpdated": f"ge{jour(data_interval_start)}"}
        ressources = []
        # ÉTAPE 1 : boucle de pagination de la séance 1, qui remplit `ressources`
        #   - r = requests.get(url, params=requete, headers={"Accept": "application/fhir+json"}, timeout=30)
        #   - r.raise_for_status() : une erreur HTTP fait échouer la tâche, donc déclenche un retry
        #   - ajouter les ressources de bundle["entry"], suivre le lien « next », puis requete = None
        while url:
            r = requests.get(url, params=requete, headers={"Accept": "application/fhir+json"}, timeout=30)
            r.raise_for_status()
            bundle = r.json()
            ressources += [e["resource"] for e in bundle.get("entry", [])
                           if e.get("resource", {}).get("resourceType") == "Observation"]
            # le lien « next » contient déjà les paramètres de la page suivante
            url = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
            requete = None
        chemin.write_text("".join(json.dumps(o) + "\n" for o in ressources))
        print(len(ressources), "ressources écrites dans", chemin)
        return str(chemin)                            # XCom : un chemin, pas les données

    @task
    def aplatir(chemin: str) -> str:
        """Étape 2 : une ligne par Observation (id, patient, date, statut, valeur, unite), en Parquet."""
        import pandas as pd

        # ÉTAPE 2 : lire le NDJSON ligne par ligne (json.loads), construire un DataFrame,
        # l'écrire avec df.to_parquet(sortie, index=False) et renvoyer str(sortie)
        lignes = []
        for ligne in Path(chemin).read_text().splitlines():
            if not ligne.strip():
                continue
            o = json.loads(ligne)
            q = o.get("valueQuantity") or {}                  # absent pour les mesures annulées
            reference = (o.get("subject") or {}).get("reference") or ""
            lignes.append({
                "id": o.get("id"),
                "patient": reference.split("/")[-1] or None,  # « Patient/p-0001 » → « p-0001 »
                "date": o.get("effectiveDateTime"),
                "statut": o.get("status"),
                "valeur": q.get("value"),
                "unite": q.get("code"),
            })
        df = pd.DataFrame(lignes, columns=["id", "patient", "date", "statut", "valeur", "unite"])
        df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce")

        sortie = DONNEES / "plat" / f"{Path(chemin).stem}.parquet"
        sortie.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(sortie, index=False)
        print(len(df), "lignes aplaties dans", sortie)
        print("Unités :", df["unite"].value_counts(dropna=False).to_dict())
        return str(sortie)

    @task
    def valider(chemin: str) -> str:
        """Étape 3 : schéma Pandera ; que faire des lignes invalides ?"""
        import pandas as pd
        import pandera.pandas as pa

        # ÉTAPE 3 : schéma avec unite dans UNITES, valeur > 0, patient non nul ;
        # écrire les lignes valides en Parquet et renvoyer le chemin
        df = pd.read_parquet(chemin)
        schema = pa.DataFrameSchema({
            "patient": pa.Column(nullable=False),                                  # patient non nul
            "valeur": pa.Column(checks=pa.Check.gt(0), nullable=False),            # valeur > 0
            "unite": pa.Column(checks=pa.Check.isin(UNITES), nullable=False),      # unité connue
        })
        try:
            schema.validate(df, lazy=True)           # lazy : recueille toutes les erreurs d'un coup
            invalides = set()
        except pa.errors.SchemaErrors as erreurs:
            invalides = set(erreurs.failure_cases["index"].dropna().astype(int))
            print("Motifs de rejet :")
            print(erreurs.failure_cases.groupby(["column", "check"], dropna=False).size().to_string())

        valides = df.drop(index=list(invalides))     # les lignes invalides sont écartées et comptées
        sortie = DONNEES / "valide" / Path(chemin).name
        sortie.parent.mkdir(parents=True, exist_ok=True)
        valides.to_parquet(sortie, index=False)
        print(f"{len(valides)} lignes valides, {len(invalides)} rejetées sur {len(df)}")
        return str(sortie)

    @task(outlets=[glycemies])
    def charger(chemin: str, data_interval_start=None):
        """Étape 4 : DELETE + INSERT du jour dans donnees/entrepot.duckdb, donc rejouable sans doublon."""
        import duckdb

        # ÉTAPE 4 : table glycemies (valeur convertie en mg/dL comme en séance 1),
        # suppression des lignes du jour puis insertion depuis read_parquet(chemin)
        j = jour(data_interval_start)
        con = duckdb.connect(str(DONNEES / "entrepot.duckdb"))
        try:
            con.execute("""
                create table if not exists glycemies (
                    observation_id varchar, patient_id varchar, mesure_le timestamp, jour date,
                    valeur_source double, unite_source varchar, valeur_mg_dl double)
            """)
            con.execute("delete from glycemies where jour = cast(? as date)", [j])   # idempotence
            con.execute("""
                insert into glycemies
                select id, patient, cast(date as timestamp), cast(? as date), valeur, unite,
                       round(case unite when 'mg/dL'  then valeur
                                        when 'g/L'    then valeur * 100
                                        when 'mmol/L' then valeur * 18.016 end, 1)
                from read_parquet(?)
            """, [j, chemin])
            du_jour = con.execute("select count(*) from glycemies where jour = cast(? as date)", [j]).fetchall()[0][0]
            total = con.execute("select count(*) from glycemies").fetchall()[0][0]
        finally:
            con.close()
        print(f"{du_jour} glycémies chargées pour le {j} · total dans l'entrepôt : {total}")

    charger(valider(aplatir(extraire())))


fhir_glycemies_quotidien()