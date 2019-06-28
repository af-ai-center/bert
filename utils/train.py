import torch
import numpy as np
from torch.optim import Adam
from torch.nn import CrossEntropyLoss
from apex.optimizers import FP16_Optimizer
from apex.optimizers import FusedAdam
from tensorboardX import SummaryWriter
from fastprogress import master_bar, progress_bar
from seqeval.metrics import f1_score as f1_score_seqeval
from sklearn.metrics import f1_score as f1_score_sklearn

def create_optimizer(model, fp16=True, no_decay = ['bias', 'gamma', 'beta']):
    # Remove unused pooler that otherwise break Apex
    param_optimizer = list(model.named_parameters())
    param_optimizer = [n for n in param_optimizer if 'pooler' not in n[0]]

    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay_rate': 0.02},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay_rate': 0.0}
    ]
    if fp16:
        optimizer = FusedAdam(optimizer_grouped_parameters, lr=3e-5, bias_correction=False, max_grad_norm=1.0)
        optimizer = FP16_Optimizer(optimizer, dynamic_loss_scale=True)
    else:
        optimizer = Adam(optimizer_grouped_parameters, lr=3e-5)
    return optimizer


class NERTrainer(object):
    """ Trainer of BERT model """

    def __init__(self, model, train_dataloader, valid_dataloader, label_list, fp16=False):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = model
        self.model.to(self.device)
        if fp16: self.model.half()
        
        self.writer = SummaryWriter()
        
        self.loss_fct = CrossEntropyLoss()
        self.train_dataloader = train_dataloader
        self.valid_dataloader = valid_dataloader
        self.label_list = label_list
        self.fp16 = fp16

        
    def fit(self, num_epochs = 25, max_grad_norm = 2.0, learning_rate = 3e-5, warmup_proportion = 0.1):
        self.num_epochs = num_epochs
        self.learning_rate = learning_rate
        self.warmup_proportion = warmup_proportion
        
        self.optimizer = self.create_optimizer(self.fp16)
        
        self.total_steps = self.total_steps()
        
        self.accuracy_hist = np.array([])
        self.f1_score_hist = np.array([])
        self.loss_hist = np.array([])
        
        
        
        epoch_process = master_bar(range(self.num_epochs))
        for epoch in epoch_process:
            self.model.train()
            self.accuracy_hist = np.array([])
            self.f1_score_hist = np.array([])
            self.loss_hist = np.array([])
            
            for step, batch in enumerate(progress_bar(self.train_dataloader, parent=epoch_process)):
                batch = tuple(t.to(self.device) for t in batch)
                input_ids, input_mask, segment_ids, label_ids = batch
                logits = self.model(input_ids, segment_ids, input_mask)
                loss = self.loss(logits, label_ids)
                
                accuracy = self.accuracy(logits, label_ids)
                f1_score = self.f1_score_default_accuracy(logits, label_ids)
                
                self.accuracy_hist = np.append(self.accuracy_hist, accuracy)
                self.f1_score_hist = np.append(self.f1_score_hist, f1_score)
                self.loss_hist = np.append(self.loss_hist, loss.mean().item())

                
                if self.fp16:
                    self.optimizer.backward(loss)
                else:
                    loss.backward()
                
                # TODO undersök varför man vill göra det här, det får ibland modellen att inte lära sig
                #self.clip_grad_norm(max_grad_norm)
                
                global_step = self.global_step(epoch, step)
                 
                epoch_process.child.comment = ("Train F1 score: {:.2}".format(self.f1_score_hist.mean()))
                
                lr_this_step = self.update_learning_rate(global_step)
                
                self.writer.add_scalar('train/accuracy', accuracy, global_step)
                self.writer.add_scalar('train/f1_score', f1_score, global_step)
                self.writer.add_scalar('train/loss', loss.mean().item(), global_step)
                self.writer.add_scalar('train/learning_rate', lr_this_step, global_step)

                self.optimizer.step()
                self.model.zero_grad()
                
            self.validation(global_step)
                
  
    def loss(self, logits, label_ids):
        loss = self.loss_fct(logits.view(-1, self.model.num_labels), label_ids.view(-1))
        return loss
    
    def validation(self, global_step):
        self.model.eval()
        eval_loss, eval_accuracy = 0, 0
        nb_eval_steps, nb_eval_examples = 0, 0
        predictions, true_labels = [], []
        for batch in self.valid_dataloader:
            batch = tuple(t.to(self.device) for t in batch)
            b_input_ids, b_input_mask, b_segment_ids, b_labels = batch
            
            with torch.no_grad():
                tmp_eval_loss = self.model(b_input_ids, token_type_ids=b_segment_ids, attention_mask=b_input_mask, labels=b_labels)
                logits = self.model(b_input_ids, token_type_ids=b_segment_ids, attention_mask=b_input_mask)
            
            f1_score = self.f1_score_default_accuracy(logits, b_labels)
            #print("F1-Score sklearn: {}".format(f1_score))
            
            logits = logits.detach().cpu().numpy()
            label_ids = b_labels.to('cpu').numpy()
            predictions.extend([list(p) for p in np.argmax(logits, axis=2)])
            true_labels.append(label_ids)
            
            tmp_eval_accuracy = self.flat_accuracy(logits, label_ids)
            
        
            eval_loss += tmp_eval_loss.mean().item()
            eval_accuracy += tmp_eval_accuracy

            nb_eval_examples += b_input_ids.size(0)
            nb_eval_steps += 1
        
        eval_loss = eval_loss/nb_eval_steps
        eval_accuracy = eval_accuracy/nb_eval_steps
        #print("Validation loss: {}".format(eval_loss))
        #print("Validation Accuracy: {}".format(eval_accuracy))
        pred_tags = [self.label_list[p_i] for p in predictions for p_i in p]
        valid_tags = [self.label_list[l_ii] for l in true_labels for l_i in l for l_ii in l_i]
        f1_score = f1_score_seqeval(pred_tags, valid_tags)
        
        self.writer.add_scalar('validation/loss', eval_loss, global_step)
        self.writer.add_scalar('validation/accuracy', eval_accuracy, global_step)
        self.writer.add_scalar('validation/f1_score', f1_score, global_step)
        print("Validation F1-Score: {}".format(f1_score))
         
        
    def f1_score_default_accuracy(self, logits, label_ids):
        predictions , true_labels = [], []
        np_logits = logits.detach().cpu().numpy()
        np_label_ids = label_ids.cpu().numpy()
        predictions.extend([list(p) for p in np.argmax(np_logits, axis=2)])
        true_labels.append(np_label_ids)
        pred_tags = [self.label_list[p_i] for p in predictions for p_i in p]
        valid_tags = [self.label_list[l_ii] for l in true_labels for l_i in l for l_ii in l_i]
        
        if self.global_step == 0:
            print(np_logits.shape, np_label_ids.shape)
        return f1_score_seqeval(pred_tags, valid_tags)
        
    def f1_score_accuracy(self, logits, label_ids):
        np_logits = logits.detach().cpu().numpy()
        np_label_ids = label_ids.to('cpu').numpy()
        pred_flat = np.argmax(np_logits, axis=2).flatten()
        labels_flat = np_label_ids.flatten()
        return f1_score_sklearn(pred_flat, labels_flat, average='samples')
    
    # todo replace with accuracy function
    def flat_accuracy(self, preds, labels):
        pred_flat = np.argmax(preds, axis=2).flatten()
        labels_flat = labels.flatten()
        return np.sum(pred_flat == labels_flat) / len(labels_flat)

    def accuracy(self, logits, label_ids):
        np_logits = logits.detach().cpu().numpy()
        np_label_ids = label_ids.to('cpu').numpy()
        pred_flat = np.argmax(np_logits, axis=2).flatten()
        labels_flat = np_label_ids.flatten()
        return np.sum(pred_flat == labels_flat) / len(labels_flat)
    
    def global_step(self, epoch, step):
        return epoch * len(self.train_dataloader) + step
    
    def total_steps(self):
        return self.num_epochs * len(self.train_dataloader)
    
    def clip_grad_norm(self, max_grad_norm):
        torch.nn.utils.clip_grad_norm_(parameters = self.model.parameters(), max_norm=max_grad_norm)
        
    def update_learning_rate(self, global_step):
        lr_this_step = self.learning_rate * self.warmup_linear(global_step / self.total_steps, self.warmup_proportion)
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = lr_this_step
        return lr_this_step
    
    def warmup_linear(self, x, warmup = 0.002):
        if x < warmup: return x/warmup
        return 1.0 - x
    
    def create_optimizer(self, fp16=True, no_decay = ['bias', 'gamma', 'beta']):
        # Remove unused pooler that otherwise break Apex
        param_optimizer = list(self.model.named_parameters())
        param_optimizer = [n for n in param_optimizer if 'pooler' not in n[0]]
        
        optimizer_grouped_parameters = [
            {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay_rate': 0.02},
            {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay_rate': 0.0}
        ]
        if fp16:
            optimizer = FusedAdam(optimizer_grouped_parameters, lr=self.learning_rate, bias_correction=False, max_grad_norm=1.0)
            optimizer = FP16_Optimizer(optimizer, dynamic_loss_scale=True)
        else:
            optimizer = Adam(optimizer_grouped_parameters, lr=self.learning_rate)
        return optimizer
        