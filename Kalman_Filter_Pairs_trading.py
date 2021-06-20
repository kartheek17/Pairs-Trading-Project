import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pykalman import KalmanFilter
from datetime import datetime
import statsmodels.tsa.stattools as ts
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
import ffn
import warnings
warnings.filterwarnings('ignore')

%matplotlib inline


def KalmanFilterRegression(x,y): #I resued this function from an article published by Xing Tao on quantinsti

    delta = 1e-3
    trans_cov = delta / (1 - delta) * np.eye(2) # How much random walk wiggles
    obs_mat = np.expand_dims(np.vstack([[x], [np.ones(len(x))]]).T, axis=1)
    
    kf = KalmanFilter(n_dim_obs=1, n_dim_state=2, # y is 1-dimensional, (alpha, beta) is 2-dimensional
                      initial_state_mean=[0,0],
                      initial_state_covariance=np.ones((2, 2)),
                      transition_matrices=np.eye(2),
                      observation_matrices=obs_mat,
                      observation_covariance=2,
                      transition_covariance=trans_cov)
    
    # Use the observations y to get running estimates and errors for the state parameters
    state_means, state_covs = kf.filter(y.values)
    return state_means    


def KalmanFilterAverage(x): #I resued this function from an article published by Xing Tao on quantinsti
    # Construct a Kalman filter
    kf = KalmanFilter(transition_matrices = [1],
                      observation_matrices = [1],
                      initial_state_mean = 0,
                      initial_state_covariance = 1,
                      observation_covariance=1,
                      transition_covariance=.01)

    # Use the observed values of the price to get a rolling mean
    state_means, _ = kf.filter(x.values)
    state_means = pd.Series(state_means.flatten(), index=x.index)
    return state_means

def half_life(spread): #I resued this function from an article published by Xing Tao on quantinsti
    spread_lag = spread.shift(1)
    spread_lag.iloc[0] = spread_lag.iloc[1]
    
    spread_ret = spread - spread_lag
    spread_ret.iloc[0] = spread_ret.iloc[1]
    
    spread_lag2 = sm.add_constant(spread_lag)
     
    model = sm.OLS(spread_ret,spread_lag2)
    res = model.fit()
    halflife = int(round(-np.log(2) / res.params[1],0))
 
    if halflife <= 0:
        halflife = 1
    return halflife

def ind_marker(stock): #function used to identify the start time index of a pair
    index_marker = 0
    data = pd.read_csv('/.../ingestable_csvs/daily/{}.csv'.format(stock))
    prices = data.close
    for i in range(len(prices)):
        if pd.isna(prices[i]) == False:
            index_marker = i
            break
    
    return index_marker

#manual backtest of pairs trading using Kalman Filters
def kalman_backtest(sym1, sym2):
    stock1 = pd.read_csv('/.../ingestable_csvs/daily/{}.csv'.format(sym1))
    stock2 = pd.read_csv('/.../ingestable_csvs/daily/{}.csv'.format(sym2))
    s1 = stock1.close
    s2 = stock2.close
    
    yr_ret = []
    yr_sharpe = []
    
    #define the time_line
    max_start = max(ind_marker(sym1), ind_marker(sym2))
    time_line = [*range(max_start+240,len(s1), 240)]
    
    #iterating each year and running the backtest
    main_df = pd.DataFrame(columns = ['x', 'y', 'spread', 'hr', 'zScore', 'long entry', 'long exit',
                                      'num units long', 'short entry', 'short exit', 'num units short',
                                      'numUnits'])
    count = 0
    for i in time_line:
        if i == time_line[-1]:
            start = i
            end = len(s1) - 1
        else: 
            start = i
            end = i+240

        x, y = s1[start-240:end], s2[start-240:end] #used in calculating the Hedge Ratio
        ax, ay = s1[start:end], s2[start:end] #the actual info to use for the trading and return calc
        df1 = pd.DataFrame({'x':ax, 'y':ay})
        df1 = df1.reset_index(drop = True)
        
        hr = []
        test_spread = []
        zSc = []
        for d in range(start,end): #for every day in our yearly range between start and end
            inp_x = x.loc[d-240:d].reset_index(drop=True) #Kalman Filter only reads non indexed series
            inp_y = y.loc[d-240:d].reset_index(drop=True) #looking back into the past 1 yr of prices
            state_means = KalmanFilterRegression(KalmanFilterAverage(inp_x), #running Kalman Filter on past 1yr data
                                                 KalmanFilterAverage(inp_y))
            hedge_ratio = - state_means[:,0] #extract the hedge ratio series
            spread = inp_y + (inp_x * hedge_ratio) #calculate the spread over the past one year data
            test_spread.append(pd.Series(spread).iloc[-1])
            hr.append(pd.Series(hedge_ratio).iloc[-1])
            halflife = half_life(spread) #calculate the halflife over the past one year data
            meanSpread = spread.rolling(window=halflife).mean()
            stdSpread = spread.rolling(window=halflife).std()
            zScore = (spread-meanSpread)/stdSpread #calculate the realtime zScore based on mean and std derived using halflife
            zSc.append(pd.Series(zScore).iloc[-1]) #take the latest zScore and store in a list
            
        final_spread = pd.Series(test_spread).reset_index(drop=True)
        df1['spread'] = final_spread
        df1['zScore'] = pd.Series(zSc).reset_index(drop=True)
        df1['hr'] = pd.Series(hr).reset_index(drop=True)


        #####################################
        #using more stringent entryZscore (closer to 0) as the Kalman Filter hedge ratio is more sensitive to swings
        entryZscore = 1 
        exitZscore = 0

        # Set up num units long             
        df1['long entry'] = ((df1.zScore < - entryZscore) & ( df1.zScore.shift(1) > - entryZscore))
        df1['long exit'] = ((df1.zScore > - exitZscore) & (df1.zScore.shift(1) < - exitZscore)) 
        df1['num units long'] = np.nan 
        df1.loc[df1['long entry'],'num units long'] = 1 
        df1.loc[df1['long exit'],'num units long'] = 0
        df1['num units long'][0] = 0 
        df1['num units long'] = df1['num units long'].fillna(method='pad')

        # Set up num units short 
        df1['short entry'] = ((df1.zScore >  entryZscore) & ( df1.zScore.shift(1) < entryZscore))
        df1['short exit'] = ((df1.zScore < exitZscore) & (df1.zScore.shift(1) > exitZscore))
        df1.loc[df1['short entry'],'num units short'] = -1
        df1.loc[df1['short exit'],'num units short'] = 0
        df1['num units short'][0] = 0
        df1['num units short'] = df1['num units short'].fillna(method='pad')

        df1['numUnits'] = df1['num units long'] + df1['num units short']
        
        #code to calculate the actual_port_rets that gives an accurate representation of strategy returns after considering regular rebalancing of initial investment
        df1['investment'] = 0.0
        df1['actual_spread'] = 0.0
        df1['actual_port_rets'] = 0.0
        for i in range(1, len(df1)):
            if df1['numUnits'].loc[i] != 0.0:
                if (df1['numUnits'].loc[i-1] == 0.0):
                    df1['investment'].loc[i] = (df1['x'].loc[i] * abs(df1['hr'].loc[i])) + df1['y'].loc[i]
                    df1['actual_spread'].loc[i] = df1['spread'].loc[i]
                else:
                    hr_update = (abs(df1['hr'].loc[i])-abs(df1['hr'].loc[i-1]))*df1['x'].loc[i]
                    df1['investment'].loc[i] = df1['investment'].loc[i-1] + hr_update
                    df1['actual_spread'].loc[i] = (df1['x'].loc[i] * df1['hr'].loc[i-1]) + df1['y'].loc[i]
                    df1['actual_port_rets'].loc[i] = df1['numUnits'].loc[i-1]*(df1['actual_spread'].loc[i] - 
                                                                               df1['actual_spread'].loc[i-1])/(df1['investment'].loc[i-1])
            else:
                if (df1['numUnits'].loc[i-1] != 0.0):
                    df1['actual_spread'].loc[i] = (df1['x'].loc[i] * df1['hr'].loc[i-1]) + df1['y'].loc[i]
                    df1['actual_port_rets'].loc[i] = df1['numUnits'].loc[i-1]*(df1['actual_spread'].loc[i] - 
                                                                               df1['actual_spread'].loc[i-1])/(df1['investment'].loc[i-1])

        df1['actual_cum_rets'] = df1['actual_port_rets'].cumsum() + 1
        
        try:
            sharpe = ((df1['actual_port_rets'].mean() / df1['actual_port_rets'].std()) * sqrt(252)) 
        except ZeroDivisionError:
            sharpe = 0.0

        #add the ret and hr to a list
        yr_ret.append(df1['actual_cum_rets'].iloc[-1])
        yr_sharpe.append(sharpe)
        main_df = pd.concat([main_df, df1])
        
        count += 1
        print('Year {} done'.format(count))
        
    main_df = main_df.reset_index(drop=True)
    port_val = (main_df['actual_port_rets'].dropna()+1).cumprod()
    avg_daily_return = main_df['actual_port_rets'].mean()
    avg_daily_std = main_df['actual_port_rets'].std()
    try:
        annualised_sharpe = (avg_daily_return/avg_daily_std) * sqrt(252)
    except ZeroDivisionError:
        annualised_sharpe = 0.0
    total_return = port_val.iloc[-1]-1
    
    #refine port_val to fit the timeline
    port_val = port_val.reset_index(drop=True)
    shift_amt = len(s1)-len(port_val)
    port_val = port_val.reindex(range(len(s1))).shift(shift_amt)
    
    return main_df, port_val,total_return,annualised_sharpe, yr_sharpe, yr_ret 

def pairs_trade(pairs, chosen_list = None):
    
    #assign variables to output
    if chosen_list == None:
        chosen_list = [*range(len(pairs))]
    else:
        chosen_lsit = chosen_list
        
    #to get size of data / index
    s1 = pd.read_csv('/.../ingestable_csvs/daily/OMC.csv').close
    port_val_df = pd.DataFrame(columns = [list(pairs.keys())[index] for index in chosen_list], 
                               index = range(len(s1))) #create a port_df
   
    
    #loop over a list of pairs
    for i in chosen_list:
        #assign stock names to variables
        stock1 = pairs['Pair ' + str(i)][0]
        stock2 = pairs['Pair ' + str(i)][1]
        
        #run manual backtest and save output 
        res = kalman_backtest(stock1, stock2)
        
        portfolio_value = res[1]
        
        port_val_df['Pair '+str(i)] = portfolio_value #add the portfolio value to the df
        
        print('Done backtesting pair {}'.format(i))
    
    #calculating the combined portfolio value taking into account equal allocation to tradable pairs at any given time
    total_val = []
    for row in range(len(s1)):
        num_null = port_val_df.loc[row].isnull().sum()
        if num_null == len(chosen_list):
            alloc = 0
            total_val.append(np.nan)
        else:
            alloc = 1/(len(chosen_list) - num_null)
            port_val = (port_val_df.loc[row] * alloc).sum()
            total_val.append(port_val)
    total_port_val = pd.Series(total_val)
    avg_daily_return = ((total_port_val/total_port_val.shift(1))-1).mean()
    avg_daily_std = ((total_port_val/total_port_val.shift(1))-1).std()
    try:
        overall_sharpe = (avg_daily_return/avg_daily_std) * sqrt(252)
    except ZeroDivisionError:
        overall_sharpe = 0.0
    overall_vol = ((total_port_val/total_port_val.shift(1))-1).std() * sqrt(252) # annualised vol of strat
    overall_return = total_port_val.iloc[-1]-1
    
    result = [overall_return, overall_vol, overall_sharpe, total_port_val]
    return result


def read_data():

    pairs_data = pd.read_csv('/.../Mean Reversion Pairs.csv') #reading the main list of pairs
    pairs_data = pairs_data[['S1 ticker', 'S2 ticker']]

    pairs = {}
    for i in range(len(pairs_data)): #creating a dictionary of pairs data
        pairs['Pair ' + str(i)] = pairs_data.loc[i].tolist()
        
    chosen_list = [0,1,2,4,5,6,13,15,21,23,25,26,29] #list of stock pairs with strong cointegration 

    return pairs, chosen_list 

def read_results(result):
    overall_return, overall_vol, overall_sharpe, total_port_val = result
    plt.plot(total_port_val)
    print(f'total return: {round(overall_return,3)}')
    print(f'total vol: {round(overall_vol,3)}')
    print(f'total sharpe: {round(overall_sharpe,3)}')

    return

if __name__ == "__main__":
    print("Reading Data...")
    pairs, chosen_list = read_data()
    print("Running Johansen's Backtest...")
    result = pairs_trade(pairs, chosen_list = chosen_list)
    print("*********** Backtest Results ***********")
    read_results(result)
