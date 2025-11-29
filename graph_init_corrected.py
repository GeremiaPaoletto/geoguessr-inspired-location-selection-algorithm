import pyrosm
import networkx as nx
import osmnx as ox
import igraph as ig
import pandas as pd
import pickle
import time
import sys
import psutil
import os

# --- CONFIGURAZIONE CLUSTER ---
FP = "bremen-251019.osm.pbf" 
OUTPUT_PKL = "bremen_processed_graph.pkl"
NETWORK_TYPE = "driving"

def log_resource_usage():
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss / (1024 ** 3)  # GB
    print(f"   [SYS] RAM Utilizzata: {mem:.2f} GB")

print(f"--- START JOB: Elaborazione OSM su Cluster Node ---")
start_global = time.time()

# ---------------------------------------------------------
# 1. CARICAMENTO AD ALTE PRESTAZIONI (Pyrosm)
# ---------------------------------------------------------
print("\n[1/4] Ingestione PBF via Pyrosm...")
t0 = time.time()

osm = pyrosm.OSM(FP)

# --- CORREZIONE QUI ---
# Step 1: Estrai Nodi e Archi come GeoDataFrames
print("      Estraendo nodi e archi dal PBF...")
nodes_gdf, edges_gdf = osm.get_network(
    network_type=NETWORK_TYPE, 
    nodes=True
)

# Step 2: Converti i DataFrame in Grafo NetworkX
print("      Convertendo in NetworkX...")
G_nx_raw = osm.to_graph(
    nodes_gdf, 
    edges_gdf, 
    graph_type="networkx",
    network_type=NETWORK_TYPE,
    osmnx_compatible=True  # Fondamentale: imposta l'indice dei nodi all'ID OSM originale
)
# ----------------------

print(f"   Grafo Grezzo caricato in {time.time()-t0:.2f}s")
print(f"   Nodi: {len(G_nx_raw.nodes):,}, Archi: {len(G_nx_raw.edges):,}")
log_resource_usage()

# Liberiamo memoria dai dataframe intermedi
del nodes_gdf, edges_gdf

# ---------------------------------------------------------
# 2. SEMPLIFICAZIONE TOPOLOGICA (OSMnx)
# ---------------------------------------------------------
print("\n[2/4] Semplificazione Topologica (OSMnx)...")
t0 = time.time()

# Imposta CRS (Pyrosm solitamente non lo setta nel grafo NX, lo forziamo a WGS84)
G_nx_raw.graph['crs'] = 'epsg:4326'

# Semplificazione
G_simplified = ox.simplify_graph(G_nx_raw, remove_rings=False)

# Aggiunta attributi fisici (tempo e velocità)
G_simplified = ox.add_edge_speeds(G_simplified)
G_simplified = ox.add_edge_travel_times(G_simplified)

print(f"   Semplificazione completata in {time.time()-t0:.2f}s")
print(f"   Nodi Finali: {len(G_simplified.nodes):,}, Archi Finali: {len(G_simplified.edges):,}")
log_resource_usage()

del G_nx_raw

# ---------------------------------------------------------
# 3. CONVERSIONE NX -> IGRAPH (Nativa con Clean-up)
# ---------------------------------------------------------
print("\n[3/4] Conversione in iGraph...")
t0 = time.time()

# Pre-pulizia: convertiamo le liste nei tag in stringhe per evitare errori in iGraph
for u, v, data in G_simplified.edges(data=True):
    for k, val in data.items():
        if isinstance(val, list):
            data[k] = ",".join([str(x) for x in val])

# Conversione diretta
g_ig = ig.Graph.from_networkx(G_simplified)

# Creazione mappa ID (Mapping da Indice iGraph -> OSM ID originale)
# 'from_networkx' salva l'ID originale (chiave del dizionario NX) nell'attributo '_nx_name'
osmid_map = {idx: original_id for idx, original_id in enumerate(g_ig.vs["_nx_name"])}

print(f"   Conversione completata in {time.time()-t0:.2f}s")
print(f"   Grafo iGraph: {g_ig.vcount():,} nodi, {g_ig.ecount():,} archi")
log_resource_usage()

# ---------------------------------------------------------
# 4. SALVATAGGIO SERIALIZZATO
# ---------------------------------------------------------
print("\n[4/4] Salvataggio Pickle...")
data_package = {
    "graph": g_ig,
    "osmid_map": osmid_map,
    "crs": "epsg:4326"
}

with open(OUTPUT_PKL, "wb") as f:
    pickle.dump(data_package, f)

print(f"--- JOB COMPLETATO in {(time.time()-start_global)/60:.2f} minuti ---")
print(f"Output salvato in: {os.path.abspath(OUTPUT_PKL)}")