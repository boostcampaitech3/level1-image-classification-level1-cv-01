import argparse
import glob
import json
import multiprocessing
import os
import random
import re
from tqdm import tqdm
from importlib import import_module
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.optim.lr_scheduler import StepLR
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

from dataset import MaskBaseDataset, EqualDataset
from loss import create_criterion
from early_stopping import EarlyStopping

from sklearn.metrics import f1_score

def seed_everything(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)  # if use multi-GPU
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)
    random.seed(seed)


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


def grid_image(np_images, gts, preds, n=16, shuffle=False):
    batch_size = np_images.shape[0]
    assert n <= batch_size

    choices = random.choices(range(batch_size), k=n) if shuffle else list(range(n))
    figure = plt.figure(figsize=(12, 18 + 2))  # cautions: hardcoded, 이미지 크기에 따라 figsize 를 조정해야 할 수 있습니다. T.T
    plt.subplots_adjust(top=0.8)  # cautions: hardcoded, 이미지 크기에 따라 top 를 조정해야 할 수 있습니다. T.T
    n_grid = int(np.ceil(n ** 0.5))
    tasks = ["mask", "gender", "age"]
    for idx, choice in enumerate(choices):
        gt = gts[choice].item()
        pred = preds[choice].item()
        image = np_images[choice]
        #gt_decoded_labels = MaskBaseDataset.decode_multi_class(gt)
        #pred_decoded_labels = MaskBaseDataset.decode_multi_class(pred)
        gt_decoded_labels = EqualDataset.decode_multi_class(gt)
        pred_decoded_labels = EqualDataset.decode_multi_class(pred)
        title = "\n".join([
            f"{task} - gt: {gt_label}, pred: {pred_label}"
            for gt_label, pred_label, task
            in zip(gt_decoded_labels, pred_decoded_labels, tasks)
        ])

        plt.subplot(n_grid, n_grid, idx + 1, title=title)
        plt.xticks([])
        plt.yticks([])
        plt.grid(False)
        plt.imshow(image, cmap=plt.cm.binary)

    return figure


def increment_path(path, exist_ok=False):
    """ Automatically increment path, i.e. runs/exp --> runs/exp0, runs/exp1 etc.

    Args:
        path (str or pathlib.Path): f"{model_dir}/{args.name}".
        exist_ok (bool): whether increment path (increment if False).
    """
    path = Path(path)
    if (path.exists() and exist_ok) or (not path.exists()):
        return str(path)
    else:
        dirs = glob.glob(f"{path}*")
        matches = [re.search(rf"%s(\d+)" % path.stem, d) for d in dirs]
        i = [int(m.groups()[0]) for m in matches if m]
        n = max(i) + 1 if i else 2
        return f"{path}{n}"


def train(data_dir, model_dir, args):
    seed_everything(args.seed)

    save_dir = increment_path(os.path.join(model_dir, args.name))

    # -- settings
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")

    # -- dataset
    dataset_module = getattr(import_module("dataset"), args.dataset)  # default: MaskBaseDataset
    datasets = []
    for i in range(5):
        dataset = dataset_module(
            data_dir=data_dir,
            loc = i
        )
        datasets.append(dataset)
    num_classes = datasets[0].num_classes  # 18
    cls_num_list = [2780, 2050, 430, 3640, 4065, 535, 556, 410, 86, 728, 813, 107, 556, 410, 86, 728, 813, 107]

    # -- augmentation
    transform_module = getattr(import_module("dataset"), args.augmentation)  # default: AlbuAugmentation
    transform_train = transform_module(
        resize=args.resize,
        mean=dataset.mean,
        std=dataset.std,
    )
    
    transform_val_module = getattr(import_module("dataset"), "AlbuAugmentationVal")
    transform_val = transform_val_module(
        resize=args.resize,
        mean=dataset.mean,
        std=dataset.std,
    )

    # -- data_loader
    train_loaders = []
    val_loaders = []
    for dataset in datasets:
        train_set, val_set = dataset.split_dataset()

        train_loader = DataLoader(
            train_set,
            batch_size=args.batch_size,
            num_workers=multiprocessing.cpu_count() // 2,
            shuffle=True,
            pin_memory=use_cuda,
            drop_last=True,
        )

        val_loader = DataLoader(
            val_set,
            batch_size=args.valid_batch_size,
            num_workers=multiprocessing.cpu_count() // 2,
            shuffle=False,
            pin_memory=use_cuda,
            drop_last=True,
        )

        train_loaders.append(train_loader)
        val_loaders.append(val_loader)

    # -- model
    model_module1 = getattr(import_module("model"), args.model1)  # default: BaseModel
    model_module2 = getattr(import_module("model"), args.model2)  # default: BaseModel
    model_module3 = getattr(import_module("model"), args.model3)  # default: BaseModel
    model_module4 = getattr(import_module("model"), args.model4)  # default: BaseModel
    model_module5 = getattr(import_module("model"), args.model5)  # default: BaseModel

    models = []

    model1 = model_module1(
        num_classes=num_classes
    ).to(device)
    model1 = torch.nn.DataParallel(model1)
    models.append(model1)

    model2 = model_module2(
        num_classes=num_classes
    ).to(device)
    model2 = torch.nn.DataParallel(model2)
    models.append(model2)

    model3 = model_module3(
        num_classes=num_classes
    ).to(device)
    model3 = torch.nn.DataParallel(model3)
    models.append(model3)

    model4 = model_module4(
        num_classes=num_classes
    ).to(device)
    model4 = torch.nn.DataParallel(model4)
    models.append(model4)

    model5 = model_module5(
        num_classes=num_classes
    ).to(device)
    model5 = torch.nn.DataParallel(model5)
    models.append(model5)



    # -- loss & metric
    criterion = create_criterion(args.criterion, cls_num_list)  # default: cross_entropy
    opt_module = getattr(import_module("torch.optim"), args.optimizer)  # default: Adam
    optimizers = []
    schedulers = []
    for i in range(5):
        optimizer = opt_module(
            filter(lambda p: p.requires_grad, models[i].parameters()),
            lr=args.lr,
            weight_decay=5e-4
        )
        scheduler = StepLR(optimizer, args.lr_decay_step, gamma=0.5)
        optimizers.append(optimizer)
        schedulers.append(scheduler)

    # -- logging
    logger = SummaryWriter(log_dir=save_dir)
    with open(os.path.join(save_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(vars(args), f, ensure_ascii=False, indent=4)

    best_val_accs = [0] * 5
    best_val_losses = [np.inf] * 5
    best_f1_scores = [0] * 5
    for epoch in range(args.epochs):
        for i in range(5):
            if i == 0: print("Model : ", args.model1)
            elif i == 1: print("Model : ", args.model2)
            elif i == 2: print("Model : ", args.model3)
            elif i == 3: print("Model : ", args.model4)
            else: print("Model : ", args.model5)

            best_val_acc = best_val_accs[i]
            best_val_loss = best_val_losses[i]
            best_f1_score = best_f1_scores[i]

            torch.cuda.empty_cache()
            # train loop
            models[i].train()
            datasets[i].set_transform(transform_train)

            loss_value = 0
            matches = 0
            temp_loss_value = 0
            temp_matches = 0
            y_true, y_pred = [], []

            for idx, train_batch in enumerate(tqdm(train_loaders[i])):
                inputs, labels = train_batch
                inputs = inputs.to(device)
                labels = labels.to(device)

                optimizers[i].zero_grad()

                outs = models[i](inputs)
                preds = torch.argmax(outs, dim=-1)
                loss = criterion(outs, labels)

                y_true.extend(labels.tolist())
                y_pred.extend(preds.tolist())

                loss.backward()
                optimizers[i].step()

                loss_value += loss.item()
                temp_loss_value += loss.item()
                matches += (preds == labels).sum().item()
                temp_matches += (preds == labels).sum().item()
                if (idx + 1) % args.log_interval == 0:
                    temp_train_loss = temp_loss_value / args.log_interval
                    temp_train_acc = temp_matches / args.batch_size / args.log_interval

                    logger.add_scalar("Train/loss", temp_train_loss, epoch * len(train_loaders[i]) + idx)
                    logger.add_scalar("Train/accuracy", temp_train_acc, epoch * len(train_loaders[i]) + idx)

                    temp_loss_value = 0
                    temp_matches = 0

            train_loss = loss_value / len(train_loaders[i])
            train_acc = matches / (args.batch_size *len(train_loaders[i]))
            f1 = f1_score(y_pred, y_true, average='macro')
            current_lr = get_lr(optimizers[i])
            print(
                f"Epoch[{epoch+1}/{args.epochs}] || F1 score {f1:4.4} || "
                f"training accuracy {train_acc:4.2%} || training loss {train_loss:4.4} || lr {current_lr} || "
            )
            schedulers[i].step()
            torch.cuda.empty_cache()

            # val loop
            datasets[i].set_transform(transform_val)
            with torch.no_grad():
                print("Calculating validation results...")
                models[i].eval()
                val_loss_items = []
                val_acc_items = []
                figure = None
                y_true, y_pred = [], []

                for val_batch in val_loaders[i]:
                    inputs, labels = val_batch
                    inputs = inputs.to(device)
                    labels = labels.to(device)

                    outs = models[i](inputs)
                    preds = torch.argmax(outs, dim=-1)

                    y_true.extend(labels.tolist())
                    y_pred.extend(preds.tolist())

                    loss_item = criterion(outs, labels).item()
                    acc_item = (labels == preds).sum().item()
                    val_loss_items.append(loss_item)
                    val_acc_items.append(acc_item)

                    if figure is None:
                        inputs_np = torch.clone(inputs).detach().cpu().permute(0, 2, 3, 1).numpy()
                        inputs_np = dataset_module.denormalize_image(inputs_np, dataset.mean, dataset.std)
                        figure = grid_image(
                            inputs_np, labels, preds, n=16, shuffle=args.dataset != "MaskSplitByProfileDataset"
                        )

                val_loss = np.sum(val_loss_items) / len(val_loaders[i])
                val_acc = np.sum(val_acc_items) / (args.valid_batch_size * len(val_loaders[i]))
                f1 = f1_score(y_pred, y_true, average='macro')

                best_val_acc = max(best_val_acc, val_acc)
                best_val_loss = min(best_val_loss, val_loss)
                best_val_accs[i] = best_val_acc
                best_val_losses[i] = best_val_loss
                if f1 > best_f1_score: #val_acc > best_val_acc and val_loss < best_val_loss:
                    print(f"----New best model for val f1 score : {f1:4.4}! saving the best model..----")
                    torch.save(models[i].module.state_dict(), f"{save_dir}/model{i}_best.pth")
                    best_f1_scores[i] = f1
                    best_f1_score = f1
                torch.save(models[i].module.state_dict(), f"{save_dir}/model{i}_last.pth")
                print(
                    f"[Val] || F1 score : {f1:4.4}, acc : {val_acc:4.2%}, loss: {val_loss:4.2} || \n"
                    f"best F1 score {best_f1_score:4.4}, best acc : {best_val_acc:4.2%}, best loss: {best_val_loss:4.2}"
                )

                logger.add_scalar("Val/loss", val_loss, epoch)
                logger.add_scalar("Val/accuracy", val_acc, epoch)
                logger.add_scalar("Val/F1", f1, epoch)
                logger.add_figure("results", figure, epoch)
                print()

            early_stop = EarlyStopping()(val_loss, models[i])
            if early_stop:
                print("early stop!!!")
                break

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # Data and model checkpoints directories
    parser.add_argument('--seed', type=int, default=42, help='random seed (default: 42)')
    parser.add_argument('--epochs', type=int, default=1, help='number of epochs to train (default: 1)')
    parser.add_argument('--dataset', type=str, default='EqualDataset', help='dataset augmentation type (default: MaskBaseDataset)')
    parser.add_argument('--augmentation', type=str, default='AlbuAugmentation', help='data augmentation type (default: BaseAugmentation)')
    parser.add_argument("--resize", nargs="+", type=int, default=[384, 384], help='resize size for image when training')
    parser.add_argument('--batch_size', type=int, default=16, help='input batch size for training (default: 64)')
    parser.add_argument('--valid_batch_size', type=int, default=32, help='input batch size for validing (default: 1000)')
    parser.add_argument('--model1', type=str, default='efficientnet_b4', help='model type (default: BaseModel)')
    parser.add_argument('--model2', type=str, default='beit_base_patch16_384', help='model type (default: BaseModel)')
    parser.add_argument('--model3', type=str, default='vit_base_patch16_384', help='model type (default: BaseModel)')
    parser.add_argument('--model4', type=str, default='swin_base_patch4_window12_384', help='model type (default: BaseModel)')
    parser.add_argument('--model5', type=str, default='vit_small_r26_s32_384', help='model type (default: BaseModel)')
    parser.add_argument('--optimizer', type=str, default='Adam', help='optimizer type (default: Adam)')
    parser.add_argument('--lr', type=float, default=1e-5, help='learning rate (default: 1e-3)')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='ratio for validaton (default: 0.2)')
    parser.add_argument('--criterion', type=str, default='LDAM', help='criterion type (default: cross_entropy)')
    parser.add_argument('--lr_decay_step', type=int, default=20, help='learning rate scheduler deacy step (default: 20)')
    parser.add_argument('--log_interval', type=int, default=20, help='how many batches to wait before logging training status')
    parser.add_argument('--name', default='exp', help='model save at {SM_MODEL_DIR}/{name}')

    # Container environment
    # parser.add_argument('--data_dir', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', '/opt/ml/input/data/train/images'))
    parser.add_argument('--data_dir', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', '/opt/ml/input/data/train/label.csv'))
    parser.add_argument('--model_dir', type=str, default=os.environ.get('SM_MODEL_DIR', '/opt/ml/code/model'))

    args = parser.parse_args()
    print(args)

    data_dir = args.data_dir
    model_dir = args.model_dir

    train(data_dir, model_dir, args)