import argparse
import configparser
import numpy as np
import torch
import torch.nn as nn
import scipy.sparse as sp
import torch.optim as optim
import torch.nn.functional as F
import pandas as pd
import time
import sys
import os
from model import*
from utils import*
import scipy.sparse as sp
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import scale
curPath = os.path.abspath(os.path.dirname(__file__))
rootPath = os.path.split(curPath)[0]
sys.path.append(rootPath)

def to_torch_sparse_tensor(x, device='cpu'):
    if not sp.isspmatrix_coo(x):
        x = sp.coo_matrix(x)
    row, col = x.row, x.col
    data = x.data

    indices = torch.from_numpy(np.asarray([row, col]).astype('int64')).long()
    values = torch.from_numpy(data.astype(np.float32))
    th_sparse_tensor = torch.sparse.FloatTensor(indices, values,
                                                x.shape).to(device)

    return th_sparse_tensor

def tensor_from_numpy(x, device='cpu'):
    return torch.from_numpy(x).to(device)

def globally_normalize_bipartite_adjacency(adjacencies, symmetric=False):

    row_sum = [np.sum(adj, axis=1) for adj in adjacencies]
    col_sum = [np.sum(adj, axis=0) for adj in adjacencies]

    for i in range(len(row_sum)):
        row_sum[i][row_sum[i] == 0] = np.inf
        col_sum[i][col_sum[i] == 0] = np.inf
    degree_row_inv = [1./r for r in row_sum]
    degree_row_inv_sqrt = [1./np.sqrt(r) for r in row_sum]
    degree_col_inv_sqrt = [1./np.sqrt(c) for c in col_sum]
    normalized_adj = []
    if symmetric:
        for i, adj in enumerate(adjacencies):
            normalized_adj.append(np.diag(degree_row_inv_sqrt[i]).dot(adj).dot(np.diag(degree_col_inv_sqrt[i])))
    else:
        for i, adj in enumerate(adjacencies):
            normalized_adj.append(np.diag(degree_row_inv[i]).dot(adj))
    return normalized_adj


def get_k_fold_data(k, data):
    data = data.values
    X, y = data[:, :], data[:, -1]
    sfolder = StratifiedKFold(n_splits=k, shuffle=True)

    train_data = []
    test_data = []
    train_label = []
    test_label = []

    for train, test in sfolder.split(X, y):
        train_data.append(X[train])
        test_data.append(X[test])
        train_label.append(y[train])
        test_label.append(y[test])
    return train_data, test_data


def AUC(label, prob):
    return roc_auc_score(label, prob)


def true_positive(pred, target):
    return ((pred == 1) & (target == 1)).sum().clone().detach().requires_grad_(False)


def true_negative(pred, target):
    return ((pred == 0) & (target == 0)).sum().clone().detach().requires_grad_(False)


def false_positive(pred, target):
    return ((pred == 1) & (target == 0)).sum().clone().detach().requires_grad_(False)


def false_negative(pred, target):
    return ((pred == 0) & (target == 1)).sum().clone().detach().requires_grad_(False)


def precision(pred, target):
    tp = true_positive(pred, target).to(torch.float)
    fp = false_positive(pred, target).to(torch.float)

    out = tp / (tp + fp)
    out[torch.isnan(out)] = 0

    return out


def sensitivity(pred, target):
    tp = true_positive(pred, target).to(torch.float)
    fn = false_negative(pred, target).to(torch.float)

    out = tp / (tp + fn)
    out[torch.isnan(out)] = 0

    return out

def specificity(pred, target):
    tn = true_negative(pred, target).to(torch.float)
    fp = false_positive(pred, target).to(torch.float)

    out = tn/(tn+fp)
    out[torch.isnan(out)] = 0

    return out


def MCC(pred,target):
    tp = true_positive(pred, target).to(torch.float)
    tn = true_negative(pred, target).to(torch.float)
    fp = false_positive(pred, target).to(torch.float)
    fn = false_negative(pred, target).to(torch.float)

    out = (tp*tn-fp*fn)/math.sqrt((tp+fp)*(tn+fn)*(tp+fn)*(tn+fp))
    out[torch.isnan(out)] = 0

    return out

def accuracy(pred, target):
    tp = true_positive(pred, target).to(torch.float)
    tn = true_negative(pred, target).to(torch.float)
    fp = false_positive(pred, target).to(torch.float)
    fn = false_negative(pred, target).to(torch.float)
    out = (tp+tn)/(tp+tn+fn+fp)
    out[torch.isnan(out)] = 0

    return out


def FPR(pred, target):
    fp = false_positive(pred, target).to(torch.float)
    tn = true_negative(pred, target).to(torch.float)
    out = fp/(fp+tn)
    out[torch.isnan(out)] = 0
    return out


def TPR(pred, target):
    tp = true_positive(pred, target).to(torch.float)
    fn = false_negative(pred, target).to(torch.float)
    out = tp/(tp+fn)
    out[torch.isnan(out)] = 0
    return out


def printN(pred, target):
    TP = true_positive(pred, target)
    TN = true_negative(pred, target)
    FP = false_positive(pred, target)
    FN = false_negative(pred, target)
    print("TN:{},TP:{},FP:{},FN:{}".format(TN, TP, FP, FN))
    return TP,TN,FP,FN


def performance(tp,tn,fp,fn):
    final_tp = 0
    final_tn = 0
    final_fp = 0
    final_fn = 0
    for i in range(len(tp)):
        final_fn += fn[i]
        final_fp += fp[i]
        final_tn += tn[i]
        final_tp += tp[i]
    print("TN:{},TP:{},FP:{},FN:{}".format(final_tn, final_tp, final_fp, final_fn))
    ACC = (final_tp + final_tn) /float (final_tp + final_tn + final_fn + final_fp)
    Sen = final_tp / float(final_tp+ final_fn)
    Spe = final_tn/float(final_tn+final_fp)
    Pre = final_tp / float(final_tp + final_fp)
    MCC = (final_tp*final_tn-final_fp*final_fn)/float(math.sqrt((final_tp+final_fp)*(final_tn+final_fn)*(final_tp+final_fn)*(final_tn+final_fp)))
    FPR = final_fp/float(final_fp+final_tn)
    return ACC,Sen, Spe,Pre,MCC,FPR


DEVICE = torch.device('cpu')
SCORES = torch.tensor([-1, 1]).to(DEVICE)

class GatedGraphConvLayer(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(GatedGraphConvLayer, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.W = nn.Linear(in_channels, out_channels)
        self.U = nn.Linear(in_channels, out_channels)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x, adj):
        h = self.W(x)
        m = torch.matmul(adj, h)
        r = self.sigmoid(self.U(x))
        h_prime = torch.mul(m, r)
        return h_prime
    
class GatedGraphConvNet(nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super(GatedGraphConvNet, self).__init__()
        self.in_channels = in_channels
        self.hidden_channels = hidden_channels
        self.out_channels = out_channels
        self.conv1 = GatedGraphConvLayer(in_channels, hidden_channels)
        self.conv2 = GatedGraphConvLayer(hidden_channels, out_channels)
        self.fc = nn.Linear(out_channels, 1)

    def forward(self, x, adj):
        x = F.relu(self.conv1(x, adj))
        x = F.relu(self.conv2(x, adj))
        x = torch.mean(x, dim=0)
        x = self.fc(x)
        return x

class GatedGraphConvNet(nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super(GatedGraphConvNet, self).__init__()
        self.in_channels = in_channels
        self.hidden_channels = hidden_channels
        self.out_channels = out_channels
        self.conv1 = GatedGraphConvLayer(in_channels, hidden_channels)
        self.conv2 = GatedGraphConvLayer(hidden_channels, out_channels)
        self.fc = nn.Linear(out_channels, 1)

    def forward(self, x, adj):
        x = F.relu(self.conv1(x, adj))
        x = F.relu(self.conv2(x, adj))
        x = torch.mean(x, dim=0)
        x = self.fc(x)
   
        gate1 = self.conv1.sigmoid(self.conv1.U(x))
        gate2 = self.conv2.sigmoid(self.conv2.U(x))
        return x, gate1, gate2

