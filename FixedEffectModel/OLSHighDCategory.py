from FixedEffectModel.DemeanDataframe import demean_dataframe
from FixedEffectModel.FormTransfer import form_transfer
from FixedEffectModel.OLSFixed import OLSFixed
from FixedEffectModel.RobustErr import robust_err
from FixedEffectModel.ClusterErr import *
from FixedEffectModel.CalDf import cal_df
from FixedEffectModel.CalFullModel import cal_fullmodel
from FixedEffectModel.Forg import forg

from statsmodels.iolib import SimpleTable
from statsmodels.compat import lrange
import statsmodels.api as sm
from scipy.stats import t
from scipy.stats import f
import numpy as np
import pandas as pd
import time


def ols_high_d_category(data_df, formula=None, robust=False, c_method='cgm', psdef=True, epsilon=1e-8, max_iter=1e6,
                        debug=False):
    """

    :param data_df: Dataframe of relevant data
    :type data_df: pd.DataFrame

    :param formula: Formula takes the form of dependent_variable~continuous_variable|fixed_effect|clusters
    :type formula: str

    :param robust: bool value of whether to get a robust variance
    :type robust: bool

    # Todo: if we have two methods then surely this is a switch bool not a string input?
    :param c_method: method used to calculate multi-way clusters variance. Possible choices are:
            - 'cgm'
            - 'cgm2'
    :type c_method: str

    :param psdef:if True, replace negative eigenvalue of variance matrix with 0 (only in multi-way clusters variance)
    :type psdef: bool

    # todo: Or are these next two var's technically complex?
    :param epsilon: tolerance of the demean process
    :type epsilon: float

    :param max_iter: max iteration of the demean process
    :type max_iter: float

    :param debug: If true then print all individual stage prints, defaults to false.
    :type debug: bool

    :return:params,df,bse,tvalues,pvalues,rsquared,rsquared_adj,fvalue,f_pvalue,variance_matrix,fittedvalues,resid,summary

    Example
    -------
    y~x+x2|id+firm|id'

    """

    out_col, consist_col, category_col, cluster_col = form_transfer(formula)
    if debug:
        print('dependent variable(s):', out_col)
        print('continuous variables:', consist_col)
        print('category variables(fixed effects):', category_col)
        print('cluster variables:', cluster_col)

    consist_var = []
    if category_col[0] == '0':
        demeaned_df = data_df.copy()
        const_consist = sm.add_constant(demeaned_df[consist_col])
        print(consist_col)
        consist_col = ['const'] + consist_col
        demeaned_df['const'] = const_consist['const']
        print('Since the model does not have fixed effect, add an intercept.')
        rank = 0
    else:
        for i in consist_col:
            consist_var.append(i)
        consist_var.append(out_col[0])
        start = time.time()
        demeaned_df = demean_dataframe(data_df, consist_var, category_col, epsilon, max_iter)
        end = time.time()
        print('demean time:',forg((end - start),4),'s')
        start = time.process_time()
        rank = cal_df(data_df, category_col)
        end = time.process_time()
        print('time used to calculate degree of freedom of category variables:',forg((end - start),4),'s')
        print('degree of freedom of category variables:', rank)

    model = sm.OLS(demeaned_df[out_col], demeaned_df[consist_col])
    result = model.fit()
    demeaned_df['resid'] = result.resid

    n = demeaned_df.shape[0]
    k = len(consist_col)
    f_result = OLSFixed()
    f_result.out_col = out_col
    f_result.consist_col = consist_col
    f_result.category_col = category_col
    f_result.data_df = data_df.copy()
    f_result.demeaned_df = demeaned_df
    f_result.params = result.params
    f_result.df = result.df_resid - rank

    if (len(cluster_col) == 0) & (robust is False):
        std_error = result.bse * np.sqrt((n - k) / (n - k - rank))
        covariance_matrix = result.normalized_cov_params * result.scale * result.df_resid / f_result.df
    elif (len(cluster_col) == 0) & (robust is True):
        start = time.process_time()
        covariance_matrix = robust_err(demeaned_df, consist_col, n, k, rank)
        end = time.process_time()
        print('time used to calculate robust covariance matrix:',forg((end - start),4),'s')
        std_error = np.sqrt(np.diag(covariance_matrix))
    else:
        if category_col[0] == '0':
            nested = False
        else:
            start = time.process_time()
            nested = is_nested(demeaned_df, category_col, cluster_col, consist_col)
            end = time.process_time()
            print('category variable(s) is_nested in cluster variables:', nested)
            print('time used to define nested or not:', end - start)

        # if nested or c_method != 'cgm':
        #     f_result.df = min(min_clust(data_df, cluster_col) - 1, f_result.df)

        start = time.process_time()
        covariance_matrix = clustered_error(demeaned_df, consist_col, cluster_col, n, k, rank, nested=nested,
                                            c_method=c_method, psdef=psdef)
        end = time.process_time()
        print('time used to calculate clustered covariance matrix:',forg((end - start),4),'s')
        std_error = np.sqrt(np.diag(covariance_matrix))

    f_result.bse = std_error
    # print(f_result.bse)
    f_result.variance_matrix = covariance_matrix
    f_result.tvalues = f_result.params / f_result.bse
    f_result.pvalues = pd.Series(2 * t.sf(np.abs(f_result.tvalues), f_result.df), index=list(result.params.index))
    f_result.rsquared = result.rsquared
    f_result.rsquared_adj = 1 - (len(data_df) - 1) / (result.df_resid - rank) * (1 - result.rsquared)
    start = time.process_time()
    tmp1 = np.linalg.solve(f_result.variance_matrix, np.mat(f_result.params).T)
    tmp2 = np.dot(np.mat(f_result.params), tmp1)
    f_result.fvalue = tmp2[0, 0] / result.df_model
    end = time.process_time()
    print('time used to calculate fvalue:',forg((end - start),4),'s')
    if len(cluster_col) > 0 and c_method == 'cgm':
        f_result.f_pvalue = f.sf(f_result.fvalue, result.df_model,
                                 min(min_clust(data_df, cluster_col) - 1, f_result.df))
        f_result.f_df_proj = [result.df_model, (min(min_clust(data_df, cluster_col) - 1, f_result.df))]
    else:
        f_result.f_pvalue = f.sf(f_result.fvalue, result.df_model, f_result.df)
        f_result.f_df_proj = [result.df_model, f_result.df]

    # std err=diag( np.sqrt(result.normalized_cov_params*result.scale*result.df_resid/f_result.df) )
    f_result.fittedvalues = result.fittedvalues
    f_result.resid = result.resid
    f_result.full_rsquared, f_result.full_rsquared_adj, f_result.full_fvalue, f_result.full_f_pvalue, f_result.f_df_full\
        = cal_fullmodel(data_df, out_col, consist_col, rank, RSS=sum(result.resid ** 2))
    f_result.nobs = result.nobs
    f_result.yname = out_col
    f_result.xname = consist_col
    f_result.resid_std_err = np.sqrt(sum(result.resid ** 2) / (result.df_resid - rank))
    if len(cluster_col) == 0:
        f_result.cluster_method = 'no_cluster'
        if robust:
            f_result.Covariance_Type = 'robust'
        else:
            f_result.Covariance_Type = 'nonrobust'
    else:
        f_result.cluster_method = c_method
        f_result.Covariance_Type = 'clustered'
    return f_result  # , demeaned_df


def ols_high_d_category_multi_results(data_df, models, table_header):
    """
    This function is used to get multi results of multi models on one dataframe. During analyzing data with large data
    size and complicated, we usually have several model assumptions. By using this function, we can easily get the
    results comparison of the different models.

    :param data_df: Dataframe with relevant data
    :param models: List of models
    :param table_header: Title of summary table
    :return: summary table of results of the different models
    """
    results = []
    for model1 in models:
        results.append(ols_high_d_category(data_df,
                                           model1['consist_input'],
                                           model1['out_input'],
                                           model1['category_input'],
                                           model1['cluster_input'],
                                           formula=None,
                                           robust=False,
                                           c_method='cgm',
                                           epsilon=1e-5,
                                           max_iter=1e6))
    consist_name_list = [result.params.index.to_list() for result in results]
    consist_name_total = []
    consist_name_total.extend(consist_name_list[0])
    for i in consist_name_list[1:]:
        for j in i:
            if j not in consist_name_total:
                consist_name_total.append(j)
    index_name = []
    for name in consist_name_total:
        index_name.append(name)
        index_name.append('pvalue')
        index_name.append('std err')
    exog_len = lrange(len(results))
    lzip = []
    y_zip = []
    b_zip = np.zeros(5)
    table_content = []
    for name in consist_name_total:
        coeff_list = []
        pvalue_list = []
        std_list = []
        for i in range(len(results)):
            if name in consist_name_list[i]:
                coeff = "%#7.4g" % (results[i].params[name])
                pvalue = "%#8.2g" % (results[i].pvalues[name])
                std = "%#8.2f" % (results[i].bse[consist_name_list[i].index(name)])
                coeff_list.append(coeff)
                pvalue_list.append(pvalue)
                std_list.append(std)
            else:
                coeff = 'Nan'
                pvalue = 'Nan'
                std = 'Nan'
                coeff_list.append(coeff)
                pvalue_list.append(pvalue)
                std_list.append(std)
        table_content.append(tuple(coeff_list))
        table_content.append(tuple(pvalue_list))
        table_content.append(tuple(std_list))
    wtffff = dict(
        fmt='txt',
        # basic table formatting
        table_dec_above='=',
        table_dec_below='-',
        title_align='l',
        # basic row formatting
        row_pre='',
        row_post='',
        header_dec_below='-',
        row_dec_below=None,
        colwidths=None,
        colsep=' ',
        data_aligns="l",
        # data formats
        # data_fmt="%s",
        data_fmts=["%s"],
        # labeled alignments
        # stubs_align='l',
        stub_align='l',
        header_align='r',
        # labeled formats
        header_fmt='%s',
        stub_fmt='%s',
        header='%s',
        stub='%s',
        empty_cell='',
        empty='',
        missing='--',
    )
    a = SimpleTable(table_content,
                    table_header,
                    index_name,
                    title='multi',
                    txt_fmt=wtffff)
    print(a)
