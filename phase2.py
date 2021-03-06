import json,time,datetime,itertools,os,sqlalchemy,collections,psycopg2,logging,sys
from pprint import pprint
import pandas as pd
import numpy as np
import random
pd.options.mode.chained_assignment = None

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

def main():
    engines_door(4058)

def engines_door(case_id):
    logger.info("Running case_id {}".format(case_id))
    time1 = time.time()
    p = get_parameters(case_id)
    units_list = get_units_list(p)  
    triplets_list = get_triplets_list(p,units_list) 
    raw_df = get_raw(p)
    testedSetups = get_testedSetups(p,raw_df,units_list,triplets_list)
    insertInto_phase2(testedSetups,"phase2",p["ph2"])
    update_state(case_id)
    logger.info("case_id {} is completed in {} seconds.".format(case_id,time.time()-time1))

def get_triplets_list(p,units_list):
    buy_stop_list = []
    stop_list = []
    target_list = []
    candle,moment = translate_order('buy',p['buy'])

    if not "operator" in moment or float(moment["change"]) >= 1:
        # Cases where the purchase will be made through a market order.
        buy_stop_list = list(np.arange(-0.05,-0.001,p["space"]))
    elif float(moment["change"]) < 1:
        # Cases where the purchase will be made through a limit order.
        buy_stop_list = list(np.arange(0.001,0.05,p["space"]))
    
    target_list = list(np.arange(0.001,0.06,p["space"]))
    stop_list = list(np.arange(-0.15,-0.005,p["space"]))

    triplets_list = [target_list,stop_list,buy_stop_list]
    return list(itertools.product(*triplets_list))

def get_testedSetups(p,raw_df,units_list,triplets_list):
    testedSetups = []
    candle,moment = translate_order('buy',p['buy'])
    
    for triplet in triplets_list:
        
        target = triplet[0]
        stop = triplet[1]
        buy_stop = triplet[2]
        
        target = round(target,3)
        stop = round(stop,3)
        buy_stop = round(buy_stop,3)

        setup = {
            'TW': 0,
            'TC': 0,
            'TL': 0,
            'TP': 0,
            'TN': 0,
            'FW': 0,
            'FC': 0,
            'FL': 0,
            'FP': 0,
            'FN': 0,
            'target': target,
            'stop': stop, 
            'buy_stop': buy_stop,
        }
        aux_list = []
        last_price_list = []
        for unit in units_list:

            target_price = unit['buy_price']*(1+target)
            stop_price = unit['buy_price']*(1+stop)
            buy_stop_price = unit["buy_price"]*(1+buy_stop)

            if not "operator" in moment or float(moment["change"]) >= 1:
                if unit["buy_farthest_price"] <= buy_stop_price:
                    whether_stopped = 'T' # stopped
                else: 
                    whether_stopped = 'F' # not-stopped
            elif float(moment["change"]) < 1:
                if unit["buy_farthest_price"] >= buy_stop_price:
                    whether_stopped = 'T' # stopped
                else: 
                    whether_stopped = 'F' # not-stopped

            if unit['buy_type'] == 'all-bought':
                if unit["sell_realhighest_price"] >= target_price and unit["lowest_price"] > stop_price:
                    partition = 'W' # winner
                elif unit["sell_realhighest_price"] < target_price and unit["lowest_price"] > stop_price:
                    partition = 'C' # consolidation
                elif unit["sell_realhighest_price"] < target_price and unit["lowest_price"] <= stop_price:
                    partition = 'L' # loser
                elif unit["sell_realhighest_price"] >= target_price and unit["lowest_price"] <= stop_price:
                    start_index = unit['buy_last_executed_index'] + 1
                    end_index = unit['sell_last_executed_index']
                    raw_section = raw_df.loc[start_index:end_index] 
                    over_target_df = raw_section[raw_section.price>=target_price]
                    over_target_df['acc_volume'] = over_target_df['volume'].cumsum(axis = 0)
                    if (over_target_df.acc_volume >= float(p['max_order'])).any():
                        last_target_index = over_target_df[over_target_df.acc_volume >= float(p['max_order'])].iloc[0].name
                        first_stop_index = raw_section[raw_section.price <= round(stop_price,3)].iloc[0].name
                        if last_target_index > first_stop_index:
                            partition = 'L' # loser
                        else:
                            partition = 'W' # winner
                    else:
                        partition = 'L' # loser

            elif unit['buy_type'] == 'nothing-bought':
                partition = 'N' # nothing-bought
            elif unit['buy_type'] == 'partially-bought':
                partition = 'P' # partiallly-bought

            aux_list.append(whether_stopped + partition)

            if partition == 'C':
                last_price_list.append(unit['last_price'])
                
        for key in set(aux_list):
            setup[key] = aux_list.count(key)

        if len(last_price_list) == 0:
            setup['last_price'] = None
        else:
            if p["last_price_approach"] == "percentile":
                setup['last_price'] = np.percentile(last_price_list,int(p['percentile_last_price']))
            elif p["last_price_approach"] == "average":
                setup['last_price'] = np.mean(last_price_list)

        testedSetups.append(setup)

    return testedSetups

def write_json(data):
    # It dumps the data in a new file called "experiment<ts_now>.txt" in experiment_data directory.
    firstPart = 'builders/warehouse/setup_data/triplets'
    secondPart = data[0]['setup_file'].split('.')[0]
    thirdPart = data[0]['space']
    fourthPart = data[0]['percentile_last_price']
    path = firstPart + '_' + secondPart + '_' + thirdPart + '_' + fourthPart + '.txt'
    if os.path.exists(path):
        print('This setup has already been tested.')
    else:
        with open(path, 'w') as outfile:
            json.dump(data, outfile)

def get_raw(p):
    return pd.read_csv(p['path_historical_data'], header=None, names=['timestamp','price','volume'])
    
def get_setup(setup_file):
    dir_path = 'builders/warehouse/setup_data/'
    setup_path = dir_path + setup_file
    with open(setup_path) as f:
        return json.load(f)

def get_units_list(p):
    engine = sqlalchemy.create_engine("postgresql://postgres:spectrum@localhost/postgres")
    query = "SELECT * FROM phase1 WHERE ph1 = '{}'".format(p["ph1"])
    df = pd.read_sql_query(query,engine)
    units_dict = df.to_dict("index")
    return [value for (key,value) in units_dict.items()]

def insertInto_phase2(testedSetups,table_name,ph2):
    success = False
    while not success:
        try:
            df = pd.DataFrame(testedSetups)
            add_column(df,'ph2',ph2)
            engine = sqlalchemy.create_engine("postgresql://postgres:spectrum@localhost/postgres")
            df.to_sql(
                name = table_name,
                con = engine,
                if_exists = 'append',
                dtype={
                    "FC": sqlalchemy.types.SmallInteger(),
                    "FL": sqlalchemy.types.SmallInteger(),
                    "FN": sqlalchemy.types.SmallInteger(),
                    "FP": sqlalchemy.types.SmallInteger(),
                    "FW": sqlalchemy.types.SmallInteger(),
                    "TC": sqlalchemy.types.SmallInteger(),
                    "TL": sqlalchemy.types.SmallInteger(),
                    "TN": sqlalchemy.types.SmallInteger(),
                    "TP": sqlalchemy.types.SmallInteger(),
                    "TW": sqlalchemy.types.SmallInteger(),
                    "buy_stop": sqlalchemy.types.Numeric(precision=4,scale=3),
                    "last_price": sqlalchemy.types.Numeric(precision=6,scale=4),
                    "stop": sqlalchemy.types.Numeric(precision=4,scale=3),
                    "target": sqlalchemy.types.Numeric(precision=4,scale=3),
                    "ph2": sqlalchemy.types.String(32),
                }     
            )
            success = True
        except:
            time.sleep(random.randint(3,6))

def dataframing(units_list):
    # It receives as input the units_list and turns it into a dataframe, which is compatible to be inserted into
    # the pandas method to_sql.

    # We need to flatten all the dictionaries of units_list. Since the dictionaries have many keys with equal
    # names, the keys in the flatten state will be changed in clever way that is short but makes it distint from
    # each other.
    for i in range(len(units_list)):
        units_list[i] = flatten(units_list[i])
    return pd.DataFrame(units_list)
        
def add_column(df,column_name,filler):
    # Add column to the dataframe df. Every cell of the column will have the value filler.
    new_column = np.full((df.shape[0],1),filler)
    df[column_name] = new_column
    
def flatten(d, parent_key='', sep='_'):
    # It transforms a dictionary with multiple hierarchies to a flat one, where key only contain values that
    # don't include other keys.
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def get_parameters(case_id):
    engine = sqlalchemy.create_engine("postgresql://postgres:spectrum@localhost/postgres")
    query = "SELECT * FROM cases WHERE case_id = '{}'".format(case_id)
    df = pd.read_sql_query(query,engine)
    notYet_p = df.to_dict("list")
    p = {key:value[0] for (key,value) in notYet_p.items()}
    p["timeframe_start"] = str(p["timeframe_start"])
    p["timeframe_end"] = str(p["timeframe_end"])
    return p

def update_state(case_id):
    success = False
    while not success:
        try:
            dbname = 'postgres'
            user = 'postgres'
            host = 'localhost'
            password = 'spectrum'
            conn = psycopg2.connect(host=host,dbname=dbname,user=user,password=password)
            c = conn.cursor()
            c.execute("SELECT ph2 FROM cases WHERE case_id = {}".format(case_id))
            phase_hash = c.fetchone()[0]
            c.execute("UPDATE cases SET state = 'ph2' WHERE ph2 = '{}'".format(phase_hash))
            conn.commit()
            success = True
        except:
            time.sleep(random.randint(3,6))
            
def translate_order(mode,inputt):
# This function receives as inputt a string with the format '1-2-3_0high+30' and returns a list called 'candle' and
# a dictionary 'moment' that are useful for further calculation.
    moment = {}
    candle,moment['string'] = inputt.split('_')
    candle = candle.split('-')

    if mode == 'buy':
        index = 0
        for char in moment['string']:
            if char.isdigit():
                index = index + 1 
            else:
                break
        moment['candle'] = moment['string'][0:index]
        moment['ohlc'] = [i for i in ['open','high','low','close'] if i in moment['string']][0]
        ope = [i for i in ['+','-','*'] if i in moment['string']]
        if ope != []:
            moment['operator'] = ope[0]
            moment['change'] = moment['string'][moment['string'].find(moment['operator'])+1:]
        return candle,moment

    if mode == 'sell':
        return candle,moment

if __name__ == '__main__':
    time1 = time.time()
    main()
    time2 = time.time()
    print('---------------------------------------')
    print('Runtime: ',time2-time1)
    print('Ran at: ',datetime.datetime.fromtimestamp(time2))