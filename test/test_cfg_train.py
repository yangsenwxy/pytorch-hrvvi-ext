import random

import numpy as np
import torch
import torch.nn as nn
from torch.optim import SGD
from torch.utils.data import DataLoader
from torchvision.datasets import MNIST
from torchvision.transforms import Compose, ToTensor, Normalize, Pad

from horch.datasets import train_test_split
from horch.models.modules import Conv2d, Flatten
from horch.models.utils import summary
from horch.train import Trainer
from horch.train.lr_scheduler import CosineAnnealingLR
from horch.train.metrics import TrainLoss, Loss
from horch.train.metrics.classification import Accuracy
from horch.config import cfg

seed = 0
random.seed(0)
np.random.seed(seed)
torch.random.manual_seed(seed)


class LeNet5(nn.Sequential):

    def __init__(self):
        super().__init__(
            Conv2d(1, 6, kernel_size=5, norm_layer='default', activation='default'),
            nn.AvgPool2d(kernel_size=2, stride=2),
            Conv2d(6, 16, kernel_size=5, norm_layer='default', activation='default'),
            nn.AvgPool2d(kernel_size=2, stride=2),
            Flatten(),
            nn.Linear(8 * 8 * 16, 120),
            nn.Linear(120, 84),
            nn.Linear(84, 10),
        )


train_transform = Compose([
    Pad(2),
    ToTensor(),
    Normalize((0.1307,), (0.3081,)),
])

test_transform = Compose([
    Pad(2),
    ToTensor(),
    Normalize((0.1307,), (0.3081,)),
])

data_home = "datasets"
ds = MNIST(data_home, train=True, download=True)
ds = train_test_split(ds, test_ratio=0.1, random=True)[1]
ds_train, ds_val = train_test_split(
    ds, test_ratio=0.05, random=True,
    transform=train_transform,
    test_transform=test_transform,
)
ds_test = MNIST(data_home, train=False, download=True, transform=test_transform)
ds_test = train_test_split(ds_test, test_ratio=0.1, random=True)[1]

net = LeNet5()
criterion = nn.CrossEntropyLoss()
optimizer = SGD(net.parameters(), lr=0.05, momentum=0.9, weight_decay=1e-4, nesterov=True)
lr_scheduler = CosineAnnealingLR(optimizer, T_max=10, eta_min=0.001)

metrics = {
    'loss': TrainLoss(),
    'acc': Accuracy(),
}

test_metrics = {
    'loss': Loss(criterion),
    'acc': Accuracy(),
}

trainer = Trainer(net, criterion, optimizer, lr_scheduler,
                  metrics=metrics, save_path="./checkpoints", name="MNIST-LeNet5")

summary(net, (1, 32, 32))

train_loader = DataLoader(ds_train, batch_size=128, shuffle=True, num_workers=2, pin_memory=True)
test_loader = DataLoader(ds_test, batch_size=128)
val_loader = DataLoader(ds_val, batch_size=128)

trainer.fit(train_loader, 10, val_loader=val_loader)

trainer.evaluate(test_loader)