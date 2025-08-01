from datetime import datetime
import math
import django

# Must call setup before improrting any Django models
django.setup()

from django.conf import settings
from proteins.models import Organism, GeneFamily, Repeat, ProteinTF, ProteinRepeats, Proteomics
from proteins.util.helpers import shortuuid
import json
import requests
import os
import pandas as pd
import sys
import unicodedata
import re
from UniProtMapper import ProtMapper

def slugify(value, allow_unicode=False):
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)

def parse_array(x):
    if x is None:
        return None
    return [a.strip() for a in x.strip().split(',')]


def load_dataframe_from_excel(file, sheet_name, dtype=None):
    if not file:
        raise Exception("Missing IMPORT_DATA_FILE in settings file")
    if not os.path.exists(file):
        raise Exception(f"File {file} does not exist.")

    if dtype:
        df = pd.read_excel(file, sheet_name=sheet_name, dtype=dtype)
    else:
        df = pd.read_excel(file, sheet_name=sheet_name)
    # Set None or NaN values to None
    df = df.where(pd.notnull(df), None)
    return df


def import_organisms():
    taxonomy_ids = ['9606', '10090', '7227']

    for taxonomy_id in taxonomy_ids:
        item = Organism(id=taxonomy_id)
        print(f"Saving organism taxonomy {taxonomy_id} to db.")
        item.save() 


def get_obj_if_exists(model, **kwargs):
    try:
        obj = model.objects.get(**kwargs)
    except model.DoesNotExist: 
        obj = None
    return obj


# Will raise an exception if obj does not exist
def get_organism_obj(taxonomy_id: str):
    if not taxonomy_id:
        return None
    return Organism.objects.get(id=taxonomy_id)


# Will raise an exception if obj does not exist
def get_gene_family_obj(gene_family: str):
    if not gene_family:
        return None
    return GeneFamily.objects.get(id=gene_family)


def import_gene_family():

    df =  load_dataframe_from_excel(settings.IMPORT_DATA_FILE, sheet_name='master_proteins')

    # Get unique gene families
    gene_family_df = df[df['gene_family'].notnull()].drop_duplicates()
    print(f"Found {len(gene_family_df)} unique gene families to save")
    for row in gene_family_df.to_dict(orient='records'):
        gene_family = row['gene_family']
        parent_organism_id = row['parent_organism']
        print(f"gene_family={gene_family}, parent_organism_id={parent_organism_id}")
        parent_organism_obj = get_organism_obj(parent_organism_id)
        existing_obj = get_obj_if_exists(GeneFamily, gene_family=gene_family)
        if existing_obj:
            print(f"Gene family {gene_family} already exists. Skipped.")
        else:
            print(f"Saving gene family {gene_family} to db.")
            item = GeneFamily(gene_family=gene_family, parent_organism=parent_organism_obj)
            item.save()


def parse_microscopy_result(x):
    if x is None:
        return None

    x = x.strip(',').strip()
    
    if '(cytoplasm, activation?)' in x:
        x = x.replace('(cytoplasm, activation?)', '(cytoplasm activation?)')
    obj = dict()
    parts = x.split(',')
    for part in parts:
        pair = part.split('=')
        key = pair[0].strip()
        val = pair[1].strip()
        obj[key] = val
    return obj


def import_repeat():

    # (1) From repeats sheet we have name, dfam_id and parent organism id
    df =  load_dataframe_from_excel(settings.IMPORT_DATA_FILE, sheet_name='repeats')

    for row in df.to_dict(orient="records"):
        name = row['parent_name']
        aliases = parse_array(row['aliases'])
        parent_organism_id = row['taxonomy_id']
        parent_organism_obj = get_organism_obj(parent_organism_id)

        existing_obj = get_obj_if_exists(Repeat, name=name)
        if not existing_obj:
            obj = Repeat(
                name=name, 
                aliases=aliases, 
                dfam_id=row["dfam_id"],
                motif=row["dfam_id"],
                proteomics="more info",
                parental_organism=parent_organism_obj
            )
            obj.save()

    # (2) From master_proteins sheet we only have name
    df =  load_dataframe_from_excel(settings.IMPORT_DATA_FILE, 'master_proteins')
    df = df[df['satellite'].notnull() & (df['satellite'] != '') & (df['satellite'] != '?')]
    # print(f"Num rows = {len(df)}")

    unique_satellites = set()
    for row in df[['gene', 'satellite']].to_dict(orient='records'):
        satellite_str = row['satellite']
        if not satellite_str:
            continue
        satellites = [x.strip() for x in satellite_str.split(',')]
        for satellite in satellites:
            unique_satellites.add(satellite)

    for name in unique_satellites:
        existing_obj = get_obj_if_exists(Repeat, name=name)
        if not existing_obj:
            obj = Repeat(
                name=name, 
                proteomics="more info"
            )
            obj.save()
        

def load_jaspar_from_url(gene, tax_group):
        base_url = "https://jaspar.genereg.net/api/v1/matrix/"
        headers = {"Accept": "application/json"}
        jaspar_ids = []
        # print(gene_name)
        params = {
            "search": gene.strip(),
            "tax_group": tax_group,
            "format": "json"
        }
        response = requests.get(base_url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to get data for {gene}: HTTP {response.status_code}")
            return {
                'count': 0, 
                'error_code': response.status_code, 
                'error_msg': response.txt, 
                'next': None,
                'previous': None, 
                'results': []
            }


def get_jaspar_ids(gene, tax_group, use_cache):
        
        cache_folder = '.cache'

        jaspar_json = None
        # If use_cache then try to load from cache first
        # If not found in cache then try loading from the url
        if use_cache:
            cache_file = f"{cache_folder}/{slugify(gene)}.json"
            if os.path.exists(cache_file):
                print(f"Loading jaspar data from cache")
                with open(cache_file, 'r') as stream:
                    jaspar_json = json.load(stream)

        if jaspar_json is None:
            if not os.path.exists(cache_folder):
                os.makedirs(cache_folder)
            print(f"Loading jaspar data from url")
            jaspar_json = load_jaspar_from_url(gene, tax_group)
            with open(cache_file, 'w') as stream:
                json.dump(jaspar_json, stream, indent=2)

        jaspar_ids = [entry['matrix_id'] for entry in jaspar_json.get('results', [])]
        return jaspar_ids


def import_protein():

    df =  load_dataframe_from_excel(settings.IMPORT_DATA_FILE, sheet_name='master_proteins', dtype=str)

    for row in df.to_dict(orient='records'):
        gene = row['gene']
        if not gene:
            continue
        gene_family_obj = None
        if row['gene_family']:
            gene_family_obj = get_obj_if_exists(GeneFamily, gene_family=row['gene_family'])

        parent_organism_obj = None
        parent_organism = row['parent_organism']
        if parent_organism:
            parent_organism = int(parent_organism)
            parent_organism_obj = get_organism_obj(parent_organism)

        # Get list of jaspar matrix_ids either from local .cache folder or from url
        jasper_ids = get_jaspar_ids(gene, tax_group='vertebrates', use_cache=True)

        obj = ProteinTF(
            gene=gene,
            aliases=parse_array(row['aliases']),
            gene_type=parse_array(row['gene_type']),
            dna_binding_domain=row['dna_binding_domain'], 
            signaling_pathway=row['signaling_pathway'],
            validation_grade=row['validation_grade'],
            prediction_method=row['prediction_method'],
            microscopy_result=parse_microscopy_result(row['microscopy_result']),
            # TODO: Remove these 2 fields
            motif_enrichment=row['motif_enrichment'],
            motif_q_score=row['motif_q_score'],
            existing_images=row['existing_images'],
            existing_images_link=row['existing_images_link'],
            existing_fusion=row['existing_fusion'],
            cloned_fusion=row['cloned_fusion'],
            imaging_results=row['imaging_results'],
            notes=row['notes'],
            articles=row['articles'],
            ENSEMBL=row['ensembl'],
            UNIPROT=row['uniprot'],
            PDB=row['PDB'],
            micro_url=row['micro_url'],
            AF3=row['AF3'],
            proteomics_url=row['proteomics_url'],
            rna_url=row['rna_url'],
            # jaspar=parse_array(row['jaspar']),
            jaspar=jasper_ids,
            protein_sequence=row['protein_sequence'],
            molecular_weight=row['molecular_weight'],
            cofactor=parse_array(row['cofactor']),
            oligomerization=row['oligomerization'] if row['oligomerization'] else None,
            gene_family=gene_family_obj,
            parent_organism=parent_organism_obj
        )
        print(type(obj))
        print(f"ENSEMBL: {obj.ENSEMBL}, GENE: {obj.gene}")
        obj.save()

        protein_obj = ProteinTF.objects.get(gene=gene)
        protein_obj.save()
        print(obj.gene, obj.slug, obj)
        print(protein_obj.gene, protein_obj.slug, protein_obj)

        satellite_str = row['satellite']
        # motif_q_score = row['motif_q_score']
        # motif_enrichment = row['motif_enrichment']
        if satellite_str:
            satellites = [x.strip() for x in satellite_str.split(',')]
            # motif_q_scores = [x.strip() for x in motif_q_score.split(',')]
            # motif_enrichments = [x.strip() for x in motif_enrichment.split(',')]
            # if len(motif_q_scores) != len(motif_enrichments):
            #     raise Exception(f"Length of motif_q_score is not the same as motif_enrichment")
            index = 0
            for satellite in satellites:
                repeat_obj = Repeat.objects.get(name=satellite)
                protein_repeat_obj = ProteinRepeats(protein=protein_obj, repeat=repeat_obj)
                # protein_repeat_obj = ProteinRepeats(protein=protein_obj, repeat=repeat_obj, motif_q_score=motif_q_scores[i], motif_enrichment=motif_enrichments[i])
                protein_repeat_obj.save()
                # index += 1

def update_proteinrepeats():
    en_df = pd.read_csv(settings.IMPORT_ENRICHMENT_FILE)
    en_df.rename(columns={"Unnamed: 0": "Gene"}, inplace=True)
    en_df = en_df.where(pd.notnull(en_df), None)

    enrich_lookup = dict()
    for row in en_df.to_dict(orient="records"):
        gene = row["Gene"]
        
        for key, value in row.items():
            if key != 'Gene':
                lookup_key = gene,key.lower()
                enrich_lookup[lookup_key] = value
                

    qs_df = pd.read_csv(settings.IMPORT_QSCORE_FILE)
    qs_df.rename(columns={"Unnamed: 0": "Gene"}, inplace=True)
    qs_df = qs_df.where(pd.notnull(qs_df), None)

    qscore_lookup = dict()
    for row in qs_df.to_dict(orient="records"):
        gene = row["Gene"]
       

        for key, value in row.items():
            if key != 'Gene':
                lookup_key = gene,key.lower()
                qscore_lookup[lookup_key] = value
               


    objs = ProteinRepeats.objects.all()
    for obj in objs:
        
        lookup_key = obj.protein.gene, obj.repeat.name.lower()
        enrichment = enrich_lookup.get(lookup_key)
        # print(f"enrichment:{enrichment}, lookup_key:{lookup_key},  enrichment:{len(enrich_lookup)}")
        q_score = qscore_lookup.get(lookup_key)
        # print(f"qscore:{q_score}, lookup_key:{lookup_key}, q_score:{len(qscore_lookup)}")
        obj.motif_enrichment = enrichment if enrichment else None
        obj.motif_q_score = q_score if q_score else None
        print(f"saving protein:{obj.protein.gene}, repeat:{obj.repeat.name}, motif_enrichment:{obj.motif_enrichment}, motif_q_score:{obj.motif_q_score}")
        obj.save()

def update_proteomics():
    # file = input("Enter file: ")
    file = "C:/Users/caris/Documents/CAMPS + INTERNSHIPS/2025 Summer - GRIPS Internship/repeatome_colab/repeatome_data/proteomics_database.csv"
    df = pd.read_csv(file, dtype=str)
    
    repeat_name = 'HSat3'
    
    parent_organism_obj = None
    parent_organism = '9606'
    if parent_organism:
        parent_organism = int(parent_organism)
        parent_organism_obj = get_organism_obj(parent_organism)

    repeat_obj = get_obj_if_exists(Repeat, name=repeat_name)
    log2C_vals = {}
    significance = {}

    for row in df.to_dict(orient='records'):
        print(ProteinTF.objects.filter(UNIPROT = row[df.keys()[0]]))
        if (len(ProteinTF.objects.filter(UNIPROT = row[df.keys()[0]])) == 0):
            mapper = ProtMapper()
            result, failed = mapper.get(ids=[row[df.keys()[0]]], fields=['gene_primary', 'gene_names', 'xref_ensembl'])
            print(result)
            if len(result) != 0:
                alias_lst = str(result['Gene Names'].values[0].split(' '))
                alias_lst = '{' + alias_lst[1:len(alias_lst) - 1] + '}'
                if len(result['Gene Names'].values[0].split(' ')) == 1:
                    alias_lst = ['null']
                print(alias_lst)
                if result['Ensembl'].values[0] == '':
                    ensembl_str = 'none'
                else:
                    ensembl_str = result['Ensembl'].values[0].split('E')[1].split(' ')[0].strip(';')
                print(ensembl_str)
                protein_obj = ProteinTF(gene=result['Gene Names (primary)'].values[0], aliases = alias_lst, UNIPROT = row[df.keys()[0]], ENSEMBL = ensembl_str, parent_organism = parent_organism_obj)
                protein_obj.save()
                protein_repeat_obj = ProteinRepeats(protein=protein_obj, repeat=repeat_obj)
                protein_repeat_obj.save()
            # print(obj.gene)
            # print(obj.aliases)
            # print(obj.ENSEMBL.values[0].split(' ')[0])
        # else:
        #     obj = ProteinTF.objects.filter(UNIPROT = row[df.keys()[0]])[0]
        #     mapper = ProtMapper()
        #     result, failed = mapper.get(ids=[row[df.keys()[0]]], fields=['gene_primary', 'gene_names', 'xref_ensembl'])
        #     ens_result = result['Ensembl'].values[0].strip(';')
        #     obj.ENSEMBL = ens_result.split('ENST')[0]
        #     print(obj.gene, obj.ENSEMBL)
        #     obj.save()
        wildtype = row['WT ZF Area']
        if row['WT ZF Area'] == '-':
            wildtype = 0
        control = row['WT CT Area']
        if row['WT CT Area'] == '-':
            control = 0
        # print(row['WT ZF Area'], row['WT CT Area'])
        log2C_vals[row[df.keys()[0]]] = math.log2((int(wildtype) + 1) / (int(control) + 1))
        significance[row[df.keys()[0]]] = row[df.keys()[1]]

    if len(Proteomics.objects.filter(target=repeat_obj.name)) == 0:
        date_string = 'Aug 30th, 2021'
        cleaned_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_string)
        date_obj = datetime.strptime(cleaned_date, "%b %d, %Y")
        obj = Proteomics(
            id = shortuuid(),
            cell_type = 'breast epithelial',
            cell_line_name = 'MCF10A',
            target = repeat_obj,
            method = 'turboID targeting HSat3 using ZF-hsat3-3xHA-turboID.',
            description = 'XXXXX Description of how samples were generated, controls, mass spec machine details. XXXXX',
            date_generated = date_obj.date(),
            parent_organism = parent_organism_obj,
            significance = significance,
            log2vals = log2C_vals,
            # UNIPROT = df.keys()[0],
            x_label = df.keys()[1],
            y_label = df.keys()[2],
        )
        obj.save()

def update_jaspar():
    df =  load_dataframe_from_excel(settings.IMPORT_DATA_FILE, sheet_name='master_proteins', dtype=str)

    for gene in sorted(set(df[df['gene'].notnull()]['gene'].values)):
        if not gene:
            continue

        print(f"\n***Updating protein {gene}")
        # Get list of jaspar matrix_ids
        jasper_ids = get_jaspar_ids(gene, tax_group='vertebrates', use_cache=True)
        if jasper_ids:
            protein_obj = ProteinTF.objects.get(gene=gene)
            protein_obj.jaspar = jasper_ids
            print(f"Updating protein: {protein_obj}")
            protein_obj.save()

def save_proteins():
    for protein in ProteinTF.objects.all():
        protein.save()

def delete_all_records():
    # Delete all records in all tables
    ProteinTF.objects.all().delete()
    Repeat.objects.all().delete()
    Proteomics.objects.all().delete()
    GeneFamily.objects.all().delete()
    Organism.objects.all().delete()



if __name__ == "__main__":

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

    command = 'unknown'
    if len(sys.argv) > 1:
        command = sys.argv[1]

    if command == 'reset': 
        delete_all_records()
        import_organisms()
        import_gene_family()
        import_repeat()
        import_protein()
        update_proteinrepeats()
        update_proteomics()

    elif command == 'update_jaspar':
        update_jaspar()

    elif command == 'update_proteinrepeats':
        update_proteinrepeats()
     
    elif command == 'update_proteomics':
        update_proteomics()
        
    elif command == 'save_proteins':
        save_proteins()
           
    else:
        print(f"Usage: python backend/import_data.py <command>")
        print("Command:")        
        print("- reset to delete existing records and repopulate tables")        
        print("- update_jaspar to download jaspar data and update jaspar column in Proteintf table")
        print("- update_proteinrepeats to download enirchmend and motif data in ProteinRepeats table")
