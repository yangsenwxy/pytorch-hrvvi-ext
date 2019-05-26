import os
from datetime import datetime
from collections import defaultdict
from pathlib import Path

from toolz.curried import get, keyfilter

import torch

from ignite.engine import Engine, Events
from ignite.handlers import Timer
from tensorboardX import SummaryWriter

from horch.common import CUDA, detach
from horch.train.metrics import TrainLoss, Loss
from horch.train._utils import _prepare_batch, set_lr


def create_supervised_evaluator(model, metrics=None,
                                device=None, prepare_batch=_prepare_batch):
    if metrics is None:
        metrics = {}
    if device:
        model.to(device)

    def _inference(engine, batch):
        model.eval()
        with torch.no_grad():
            input, target = prepare_batch(batch, device=device)
            if hasattr(model, 'inference'):
                preds = model.inference(*input)
            else:
                preds = model(*input)
            if torch.is_tensor(preds):
                preds = (preds,)
            output = {
                "preds": preds,
                "target": target,
                'batch_size': input[0].size(0),
            }
            return output

    engine = Engine(_inference)

    for name, metric in metrics.items():
        metric.attach(engine, name)

    return engine


def create_supervised_trainer(
        model, criterion, optimizer, metrics=None,
        device=None, prepare_batch=_prepare_batch, fp16=False):
    if metrics is None:
        metrics = {}
    if device:
        model.to(device)

    def _update(engine, batch):
        model.train()
        optimizer.zero_grad()
        input, target = prepare_batch(batch, device=device)
        preds = model(*input)
        if torch.is_tensor(preds):
            preds = (preds,)
        loss = criterion(*preds, *target)
        if fp16:
            from apex import amp
            with amp.scale_loss(loss, optimizer) as scaled_loss:
                scaled_loss.backward()
        else:
            loss.backward()
        optimizer.step()
        output = {
            "preds": detach(preds),
            "target": detach(target),
            "loss": loss.item(),
            "batch_size": input[0].size(0),
        }
        return output

    engine = Engine(_update)
    for name, metric in metrics.items():
        metric.attach(engine, name)

    return engine


def _terminate_on_iterations(engine, iterations):
    if engine.state.iteration == iterations:
        engine.terminate()


def _evaluate(engine, evaluator, val_loader, per_epochs=1):
    if engine.state.epoch % per_epochs == 0:
        evaluator.run(val_loader)


class Trainer:

    def __init__(self, model, criterion, optimizer, lr_scheduler=None,
                 metrics=None, evaluate_metrics=None, save_path=".", name="Net"):

        self.model = model
        self.criterion = criterion
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler
        self.metrics = metrics or {}
        self.evaluate_metrics = evaluate_metrics
        if evaluate_metrics is None:
            self.evaluate_metrics = metrics.copy()
            if 'loss' in metrics and isinstance(metrics['loss'], TrainLoss):
                self.evaluate_metrics['loss'] = Loss(criterion=criterion)
        self.save_path = os.path.join(save_path, 'trainer')
        self.name = name

        current_time = datetime.now().strftime('%b%d_%H-%M-%S')
        log_dir = os.path.join(save_path, 'runs', self.name, current_time)
        self._writer = SummaryWriter(log_dir)

        self.metric_history = defaultdict(list)
        self._device = 'cuda' if CUDA else 'cpu'
        self._timer = Timer()
        self._epochs = 0

        self.model.to(self._device)

    def _log_epochs(self, engine, epochs):
        print("Epoch %d/%d" %
              (self._epochs + 1, self._epochs + 1 + epochs - engine.state.epoch))

    def _lr_scheduler_step(self, engine):
        data_loader = engine.state.dataloader
        iteration = engine.state.iteration - 1
        iters_per_epoch = len(data_loader)
        cur_iter = iteration % iters_per_epoch
        if self.lr_scheduler:
            self.lr_scheduler.step(self.epochs() + (cur_iter / iters_per_epoch))

    def _increment_epoch(self, engine):
        self._epochs += 1

    def _log_results(self, engine):
        elapsed = int(self._timer.value())
        msg = "elapsed: %ds\t" % elapsed
        for name, val in engine.state.metrics.items():
            if isinstance(val, float):
                msg += "%s: %.4f\t" % (name, val)
                self._writer.add_scalar(name, val, self.epochs())
            else:
                msg += "%s: %s\t" % (name, val)
                for i, v in enumerate(val):
                    pass
                    self._writer.add_scalar("%s-%d" % (name, i + 1), v, self.epochs())
            self.metric_history[name].append(val)
        print(msg)

    def _log_val_results(self, engine, evaluator, per_epochs=1):
        if engine.state.epoch % per_epochs != 0:
            return
        msg = "validate ------\t"
        for name, val in evaluator.state.metrics.items():
            if isinstance(val, float):
                msg += "%s: %.4f\t" % (name, val)
                self._writer.add_scalar(name, val, self.epochs())
            else:
                msg += "%s: %s\t" % (name, val)
                for i, v in enumerate(val):
                    pass
                    self._writer.add_scalar("%s-%d" % (name, i + 1), v, self.epochs())
            self.metric_history["val_" + name].append(val)
        print(msg)

    def fit(self, train_loader, epochs=1, val_loader=None, save=None, iterations=None, callbacks=(), fp16=False):

        engine = create_supervised_trainer(
            self.model, self.criterion, self.optimizer,
            self.metrics, self._device, fp16=fp16)

        # lr_scheduler
        engine.add_event_handler(
            Events.ITERATION_STARTED, self._lr_scheduler_step)

        # timer and epoch logger
        self._timer.attach(engine, start=Events.EPOCH_STARTED)
        engine.add_event_handler(Events.EPOCH_STARTED, self._log_epochs, epochs)

        if val_loader is not None:
            if isinstance(val_loader, tuple):
                val_loader, eval_per_epochs = val_loader
            else:
                eval_per_epochs = 1
            evaluator = create_supervised_evaluator(
                self.model, self.evaluate_metrics, self._device)
            engine.add_event_handler(
                Events.EPOCH_COMPLETED, _evaluate, evaluator, val_loader, eval_per_epochs)

        engine.add_event_handler(Events.EPOCH_COMPLETED, self._increment_epoch)
        engine.add_event_handler(Events.EPOCH_COMPLETED, self._log_results)
        if val_loader is not None:
            engine.add_event_handler(
                Events.EPOCH_COMPLETED, self._log_val_results, evaluator, eval_per_epochs)

        # Set checkpoint
        if save:
            checkpoint_handler = save.parse(self)
            engine.add_event_handler(
                Events.EPOCH_COMPLETED, checkpoint_handler, {"trainer": self})

        for callback in callbacks:
            engine.add_event_handler(
                Events.EPOCH_COMPLETED, _callback_wrapper(callback), self)

        if iterations:
            engine.add_event_handler(
                Events.ITERATION_COMPLETED, _terminate_on_iterations, iterations)
            epochs = 1000

        # Run
        engine.run(train_loader, epochs)

        # Return history
        hist = {metric: hist[-epochs:]
                for metric, hist in self.metric_history.items()}
        if val_loader is None:
            hist = keyfilter(lambda k: not k.startswith("val_"), hist)
        return hist

    def state_dict(self):
        s = {
            "epochs": self.epochs(),
            "model": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "lr_scheduler": None,
            "metric_history": self.metric_history,
        }
        if self.lr_scheduler:
            s["lr_scheduler"] = self.lr_scheduler.state_dict()
        return s

    def load_state_dict(self, state_dict):
        epochs, model, optimizer, lr_scheduler, metric_history = get(
            ["epochs", "model", "optimizer", "lr_scheduler", "metric_history"], state_dict)
        self._epochs = epochs
        self.model.load_state_dict(model)
        self.optimizer.load_state_dict(optimizer)
        if self.lr_scheduler and lr_scheduler:
            self.lr_scheduler.load_state_dict(lr_scheduler)
        self.metric_history = metric_history

    def save(self):
        d = Path(self.save_path)
        d.mkdir(parents=True, exist_ok=True)
        filename = "%s_trainer_%d.pth" % (self.name, self.epochs())
        fp = d / filename
        torch.save(self.state_dict(), fp)
        print("Save trainer as %s" % fp)

    def load(self):
        d = Path(self.save_path)
        pattern = "%s_trainer*.pth" % self.name
        saves = list(d.glob(pattern))
        if len(saves) == 0:
            raise FileNotFoundError("No checkpoint to load for %s in %s" % (self.name, self.save_path))
        fp = max(saves, key=lambda f: f.stat().st_mtime)
        self.load_state_dict(torch.load(fp, map_location=self._device))
        print("Load trainer from %s" % fp)

    def epochs(self):
        return self._epochs

    def evaluate(self, test_loader, evaluate_metrics=None):
        if evaluate_metrics is None:
            evaluate_metrics = self.evaluate_metrics
        evaluator = create_supervised_evaluator(
            self.model, evaluate_metrics, self._device)
        return evaluator.run(test_loader).metrics

    def set_lr(self, lr):
        set_lr(lr, self.optimizer, self.lr_scheduler)


def _callback_wrapper(f):
    def func(engine, *args, **kwargs):
        return f(*args, **kwargs)

    return func
