from flask_restful import Resource
import requests
import random
import re
import json
import os
import psycopg2
from psycopg2 import sql
import psycopg2.extras
from io import BytesIO
from flask import send_file
from fuzzywuzzy import fuzz
DATABASE_URL = os.environ['DATABASE_URL']
PYTHONIOENCODING="UTF-8"




def get_gbif_tax_from_id(gbifid: int):
    api = f"https://api.gbif.org/v1/species/{gbifid}"
    response = requests.get(api)
    content = response.json()
    return content

def get_gbif_tax_from_name(name: str):
    api = f"https://api.gbif.org/v1/species/match/?name={name}"
    response = requests.get(api)
    content = response.json()
    return content

def get_gbif_tax_from_sci_name(sci_name: str):
    api = f"https://api.gbif.org/v1/species/match/?name={sci_name},nameType=SCIENTIFIC"
    response = requests.get(api)
    content = response.json()
    return content

def get_gbif_parent(gbifkey: int):
    api= f"https://api.gbif.org/v1/species/{gbifkey}/parents"
    response = requests.get(api)
    content = response.json()
    #content = pd.json_normalize(response.json())
    return content

def get_gbif_parsed_from_id(gbifkey: int):
    api= f"https://api.gbif.org/v1/species/{gbifkey}/name"
    response = requests.get(api)
    content = response.json()
    return content

def get_gbif_parsed_from_sci_name(sci_name: str):
    api= f"https://api.gbif.org/v1/parser/name?name={sci_name}"
    response = requests.get(api)
    content = response.json()[0]
    return content


def get_gbif_synonyms(gbifkey: int):
    api= f"https://api.gbif.org/v1/species/{gbifkey}/synonyms"
    response = requests.get(api)
    content = response.json()
    return content

def test_taxInDb(connection,**kwargs):
    cur = connection.cursor()
    alreadyInDb = False
    gbifMatchMode = None
    cdTax = None
    if (kwargs.get('gbifkey') is not None):
        SQL = "SELECT count(*) AS nb FROM taxon WHERE gbifkey = %s"
        cur.execute(SQL, [kwargs.get('gbifkey')])
        gbifKeyInDb_nb, = cur.fetchone()
        if (gbifKeyInDb_nb == 1):
            if(kwargs.get('canonicalname') is not None):
                SQL = "SELECT name FROM taxon WHERE gbifkey = %s"
                cur.execute(SQL,[kwargs.get('gbifkey')])
                nameTaxDb, = cur.fetchone()
                diffTaxName = fuzz.ratio(nameTaxDb,kwargs.get('canonicalname'))
                if (diffTaxName < 0.75):
                    raise Exception("Name of the taxon does not correspond to gbifkey")
            alreadyInDb = True
            SQL = "SELECT cd_tax FROM taxon WHERE gbifkey = %s"
            cur.execute(SQL,[kwargs.get('gbifkey')])
            cdTax,  = cur.fetchone()
        elif (gbifKeyInDb_nb == 0):
            gbifMatchMode = 'gbifkey'
        else :
            raise Exception("gbifkey more than once in the database, should not be possible!")
    elif (kwargs.get('scientificname') is not None):
        SQL = "SELECT count(*) AS nb FROM taxon WHERE name_auth = %s"
        cur.execute(SQL,[kwargs.get('scientificname')])
        gbifSciInDb_nb, = cur.fetchone()
        if (gbifSciInDb_nb == 1):
            alreadyInDb = True
            SQL = "SELECT cd_tax FROM taxon WHERE name_auth = %s"
            cur.execute(SQL,[kwargs.get('scientificname')])
            cdTax,  = cur.fetchone()
        elif (gbifSciInDb_nb == 0):
            infoTax = get_gbif_tax_from_sci_name(kwargs.get('scientificname'))
            gbifMatchMode = 'scientificname'
        else:
            raise Exception("Name (with author) in the database more than once, should not be possible!")
    elif (kwargs.get('canonicalname') is not None):
        SQL = "SELECT count(*) AS nb FROM taxon WHERE name =%s"
        cur.execute(SQL,[kwargs.get('canonicalname')])
        gbifNameInDb_nb, = cur.fetchone()
        if (gbifNameInDb_nb == 1):
            alreadyInDb = True
            SQL = "SELECT cd_tax FROM taxon WHERE name = %s"
            cur.execute(SQL, [kwargs.get('canonicalname')])
            cdTax, = cur.fetchone()
        elif (gbifNameInDb_nb == 0):
            infoTax = get_gbif_tax_from_name(kwargs.get('canonicalname'))
            gbifMatchMode = 'canonicalname'
        else:
            raise Exception("Name (without author) exists more than once in the database, please provide scientificname or gbifkey instead, in order to be able to identify which taxon you are referring to")
    else:
        raise Exception("Either 'gbifkey', or 'scientificname', or 'canonicalname' should be included in the parameters in order to be able to identify the taxon")
    cur.close()
    return {'alreadyInDb': alreadyInDb, 'gbifMatchMode': gbifMatchMode, 'cdTax': cdTax}

def get_infoTax(**kwargs):
    foundGbif = False
    if (kwargs.get('gbifMatchMode') == 'gbifkey'):
        infoTax = get_gbif_tax_from_id(kwargs.get('gbifkey'))
        foundGbif = True
    elif (kwargs.get('gbifMatchMode') == 'canonicalname'):
        infoTax = get_gbif_tax_from_name(kwargs.get('canonicalname'))
    elif (kwargs.get('gbifMatchMode') == 'scientificname'):
        infoTax = get_gbif_tax_from_sci_name(kwargs.get('scientificname'))
    else:
        raise Exception("No acceptable gbifMatchMode were provided")
    if(kwargs.get('gbifMatchMode') in ('scientificname','canonicalname')):
        if(infoTax.get("matchType") != "NONE" and(infoTax.get("matchType") == "EXACT" or infoTax.get('confidence') >=90)):
            foundGbif = True
            infoTax.update(get_gbif_tax_from_id(infoTax.get('usageKey')))
    # We need to update the information as well if the taxon is of a level lower than species, because canonicalnames are given without markers, which is not the way it is in the species lists
    if(foundGbif and infoTax.get('rank') in ('SUBSPECIES','VARIETY','FORM','SUBVARIETY','SUPERSPECIES','SUBGENUS','TRIBE')):
        infoTax.update(get_gbif_parsed_from_sci_name(infoTax.get('scientificName')))
    infoTax['foundGbif'] = foundGbif
    return infoTax

def get_rank(connection,rankInput):
    cur = connection.cursor()
    SQL = "WITH a as (SELECT %s AS input) SELECT rank_name,rank_level FROM tax_rank,A WHERE gbif_bb_marker = a.input OR rank_name = a.input OR cd_rank= a.input"
    cur.execute(SQL,[rankInput])
    rank, level= cur.fetchone()
    cur.close()
    return rank, level
    

def format_inputTax(connection, acceptedName, acceptedId, **inputTax):
    hasSciName = inputTax.get('scientificname') is not None
    hasCanoName = inputTax.get('canonicalname') is not None
    hasAuth = inputTax.get('authorship')
    hasSup = inputTax.get('parentcanonicalname') is not None or inputTax.get('parentscientificname') is not None or inputTax.get('parentgbifkey') is not None
    hasRank = inputTax.get('rank')
    syno = inputTax.get('syno')
    parentTax = {'canonicalname':inputTax.get('parentcanonicalname'),'scientificname':inputTax.get('parentscientificname'),'gbifkey':inputTax.get('parentgbifkey')}
    # status: since this is the case where taxa are not found in gbif, the taxon will be noted as either synonym or doubtful
    if(syno):
        status = 'SYNONYM'
    else:
        status = 'DOUBTFUL'
    if(hasRank and hasCanoName and hasSciName and (hasSup or syno)):
        rank, level_rank = get_rank(connection,inputTax.get('rank'))
        #if (not syno):
        #    name_sup = inputTax.get('tax_sup')
        name = inputTax.get('canonicalname')
        name_auth = inputTax.get('scientificname')
    else:
        if(hasSciName):
            parsed = get_gbif_parsed_from_sci_name(inputTax.get('scientificname'))
            if(not parsed.get('parsed')):
                raise Exception("Name not found in GBIF and information insufficient to integrate in the database")
        else:
            parsed = get_gbif_parsed_from_sci_name(inputTax.get('canonicalname'))
        name=parsed.get('canonicalNameComplete')
        name_auth = parsed.get('scientificName')
        if(not hasRank):
            if(parsed.get('rankMarker') is not None):
                rank, level_rank = get_rank(connection,parsed.get('rankMarker'))
            else:
                raise Exception("No way to determine the taxon rank")
        else:
            rank, level_rank = get_rank(connection,inputTax.get('rank'))
        if(parentTax.get('canonicalname') is None):
            if(rank_level < 5):#infraspecies: the superior rank is the species which we can get by association between the genus and the epithet
                parentTax['canonicalName'] = parsed.get('genusOrAbove') + ' ' + parsed.get('specificEpithet')
            elif (rank_level == 5):
                parentTax['canonicalname'] = parsed.get('genusOrAbove')
            else:
                if(not hasSup and not syno):
                    raise Exception("No sure way to determine the superior taxon")
    if(not hasAuth and name in name_auth):
        extractAuth = name_auth.replace(name,'')
        auth = re.sub("^ *(.+) *$","\1",extractAuth)
        if(auth == ''):
            auth = None
    else:
        auth = inputTax.get('authorship')
    return {'name': name, 'name_auth': name_auth, 'auth': auth, 'tax_rank_name': rank, 'status': status, 'gbifkey': None, 'source': inputTax.get('source')}, parentTax

def format_gbif_tax(connection,**gbif_tax):
    rank, level_rank = get_rank(connection, gbif_tax.get('rank'))
    if(level_rank < 5):
        parsed = get_gbif_parsed_from_id(gbif_tax.get('key'))
        name = parsed.get('canonicalNameWithMarker')
        name_auth = parsed.get('scientificName')
    else:
        name = gbif_tax.get('canonicalName')
        name_auth = gbif_tax.get('scientificName')
    if(gbif_tax.get('syno')):
        status = 'SYNONYM'
    else:
        status = gbif_tax.get('status')
        if (status is None):
            status = gbif_tax.get('taxonomicStatus')
    parentTax = {'gbifkey': gbif_tax.get('parentKey'), 'canonicalname': gbif_tax.get('parent')}
    return {'name': name, 'name_auth': name_auth, 'auth': gbif_tax.get('authorship'), 'tax_rank_name': rank, 'status': status, 'gbifkey': gbif_tax.get('key'), 'source' : None}, parentTax

def format_parents(connection,parents):
    idParentInDb = None
    listFormatted = []
    for i in parents:
        i.update(test_taxInDb(connection,**{'gbifkey':i.get('key')}))
        if(i.get('alreadyInDb')):
            idParentInDb=i.get('cdTax')
        else:
            listFormatted.append({'name':i.get('canonicalName'), 'name_auth': i.get('scientificName'),'auth':i.get('authorship'),'tax_rank_name': i.get('rank'), 'status': i.get('taxonomicStatus'), 'gbifkey':i.get('key'), 'source': None})
    return idParentInDb, listFormatted

def acceptedId(connection,cd_tax:int):
    cur = connection.cursor()
    SQL = "SELECT COALESCE(cd_syno,cd_tax) FROM taxon WHERE cd_tax=%s"
    cur.execute(SQL,[cd_tax])
    res, =cur.fetchone()
    cur.close()
    return res

def insertTax(cursor,idParent,idSyno,**tax):
    SQL = "WITH a AS( SELECT %s AS name, %s AS name_auth, %s AS auth, %s AS name_rank, %s AS status, %s AS gbif_key, %s AS source, %s AS cd_sup, %s AS cd_syno), b AS (SELECT name, name_auth, CASE WHEN NOT auth ~ '^ *$' THEN auth ELSE NULL END AS auth, cd_rank,cd_sup::int, cd_syno::int, status, gbif_key, source::int FROM a JOIN tax_rank t ON a.name_rank=t.rank_name)  INSERT INTO taxon(name,name_auth,auth,tax_rank,cd_sup,cd_syno,status, gbifkey, source) SELECT * FROM b RETURNING cd_tax"
    cursor.execute(SQL,(tax.get('name'), tax.get('name_auth'), tax.get('auth'), tax.get('tax_rank_name'),tax.get('status'), tax.get('gbifkey'),tax.get('source'),idParent,idSyno))
    idInserted, = cursor.fetchone()
    return idInserted
    
    
# TODO : since panda does not simplify particularly the method to write a table in the postgres database, it would be better to remove all the panda dependency and keep only dictionaries...
# if the direct parent is not in the database
# testing its presence in gbif
# formatting in a way that keep only the parent which are not in the database
# inserting in the database one by one with a returning clause which gives the ID to be used in the following descendant...
# using the same kind of returning clause to get the accepted id from the thing
# in all the inserting into taxon clause, it would be possible as well to use a with clause in order to create a recursing with pseudo-table and avoid temporary table...

def manageInputTax(**inputTax):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    syno = False
    inputTax.update(test_taxInDb(connection=conn,**inputTax))
    if (not inputTax.get('alreadyInDb')):
        inputTax.update(get_infoTax(**inputTax))
        inputTax['syno'] = False
        # In case we did not find the taxon at first be it is indeed in the database
        if(inputTax.get('foundGbif')):
            recheck = test_taxInDb(connection=conn,gbifkey=inputTax.get('key'))
            inputTax['alreadyInDb']=recheck.get('alreadyInDb')
            inputTax['cdTax'] = recheck.get('cdTax')
    if (not inputTax.get('alreadyInDb')):
        # synonyms
        if(inputTax.get('foundGbif') and inputTax.get('synonym')): # synonym found through gbif, note: all synonym info from the arguments (positive, negative, precise or not) in the function will not be considered... GBIF being our backbone here!
            syno = True
            inputTax['syno'] = True
            acceptedTax = {'gbifkey':inputTax.get('acceptedUsageKey'),'scientificname': inputTax.get('accepted')}
            if acceptedTax.get('gbifkey') is None:
                acceptedTax['gbifkey']=inputTax.get('acceptedKey')
        if(not inputTax.get('foundGbif') and (inputTax.get('synogbifkey') is not None or inputTax.get('synoscientificname') is not None or inputTax.get('synocanonicalname') is not None)):
            syno = True
            inputTax['syno'] = True
            acceptedTax = {'gbifkey': inputTax.get('synogbifkey'), 'scientificname': inputTax.get('synoscientificname'), 'canonicalname': inputTax.get('synocanonicalname')}
        if(syno): 
            acceptedTax.update(test_taxInDb(connection=conn,**acceptedTax))
            if(not acceptedTax.get('alreadyInDb')):
                acceptedTax.update(get_infoTax(**acceptedTax))
                acceptedTax['syno'] = False
                recheckAccepted = test_taxInDb(connection=conn,gbifkey=acceptedTax.get('key'))
                acceptedTax['alreadyInDb'] = recheckAccepted.get('alreadyInDb')
                acceptedTax['cdTax'] = recheckAccepted.get('cdTax')
        # The smart  move I think would be to manage formats (taxa recognized or not by gbif) here in order to:
        # - get the ranks
        # - get the simplified versions of taxa before going to parents
        # - change the names of dictionaries in order to get the "accepted" taxon in one variable, synonyms or not, recognized by gbif or not
            if(not acceptedTax.get('alreadyInDb')):
                if(acceptedTax.get('foundGbif')):
                    accepted, parentTax = format_gbif_tax(connection=conn, **acceptedTax)
                else:
                    accepted, parentTax = format_inputTax(connection=conn, **acceptedTax)
            if(inputTax.get('foundGbif')):
                synonym, synoParent = format_gbif_tax(connection=conn, **inputTax)
            else:
                synonym, synoParent = format_inputTax(connection=conn, **inputTax)
        else:
            if(not inputTax.get('alreadyInDb')):
                if(inputTax.get('foundGbif')):
                    accepted, parentTax = format_gbif_tax(connection=conn, **inputTax)
                else:
                    accepted, parentTax = format_inputTax(connection=conn, acceptedName = None, acceptedId=None,**inputTax)
        if syno and acceptedTax.get('alreadyInDb'):
            parentTax = {'alreadyInDb': True}
        else:
            parentTax.update(test_taxInDb(conn,**parentTax))
        if(not parentTax.get('alreadyInDb')):
            if(accepted.get('gbifkey') is None):
                parentTax.update(get_infoTax(**parentTax))
                if (not parentTax.get('foundGbif')):
                    raise Exception('Parent taxa not found')
                parents = get_gbif_parent(parentTax.get('key'))
                parents.append(parentTax)
            else:
                parents = get_gbif_parent(accepted.get('gbifkey'))
            idParentInDb, parentsFormatted = format_parents(conn,parents)
        with conn:
            with conn.cursor() as cur:
                if(not parentTax.get('alreadyInDb')):
                    for i in range(0,len(parentsFormatted)):
                        idParentInDb = insertTax(cur,idParentInDb,None,**parentsFormatted[i])
                else:
                    idParentInDb=parentTax.get('cdTax')
                if(syno and acceptedTax.get('alreadyInDb')):
                    accId=acceptedTax.get('cdTax')
                else:
                    accId=insertTax(cur,idParentInDb,idSyno=None,**accepted)
                if(syno):
                    insertTax(cur, None, accId, **synonym)
        cur.close()
        conn.close()
    else:
        accId = acceptedId(connection=conn,cd_tax=inputTax.get('cdTax'))
        conn.close()
    return accId
