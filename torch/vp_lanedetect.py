import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import os
import numpy as np
import scipy.io
import tqdm
import time
from vpgnet_torch import VPGNet

class VP4LaneDetection:
    def __init__(self,
                model: VPGNet,
                loss_vp = nn.BCELoss(),
                loss_obj_mask = nn.BCELoss(),
                optimizer = None ,
                learning_rate = 1e-3):
        """
        Args:
            Model: VPGNet instance to train/test
            Loss_vp: Torch loss function for training the vp branch
            loss_obj_mask: Torch loss function for the overall net (after vp training phase)
            Optimizer: Torch optimizer for training
            Learning_rate: Learning rate for net (default = 1e-3)
        """
        #Checks that args are valid
        assert type(model) == VPGNet

        self.model = model
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        if torch.cuda.device_count() > 1:
            model = nn.DataParallel(model)

        model.to(device=self.device)   

        self.loss_vp = loss_vp
        self.loss_obj_mask = loss_obj_mask

        if(optimizer == None):
            self.optimizer = torch.optim.Adam(model.parameters(), learning_rate)
        else:
            self.optimizer = optimizer

        self.learning_rate = learning_rate
    


    def train(self,
            train_dataloader: DataLoader,
            validation_dataloader: DataLoader,
            num_epochs_vp: int,
            num_epochs_general: int):
        """
        Args:
            Train_dataloader: Dataloader for training dataset
            Val_dataloader: Dataloader for validation dataset
            Num_epochs_vp: Number of epochs to train vpp branch (cross-entropy)
            Num_epochs_general: Number of epochs to train entire model (L1 obj_mask Loss)
        """

        """
        Args:
            Train_dataloader: Dataloader for training dataset
            Val_dataloader: Dataloader for validation dataset
            Num_epochs_vp: Number of epochs to train vpp branch (cross-entropy)
            Num_epochs_general: Number of epochs to train entire model (L1 obj_mask Loss)
        """

        #Checking that args are valid
        assert type(train_dataloader) == DataLoader
        assert type(validation_dataloader) == DataLoader
        assert num_epochs_vp > 0
        assert num_epochs_general > 0

        self.model.train()
        for e in range(num_epochs_vp):
            start_time = time.time()
            train_loss = 0.0
            train_vp_acc = 0.0
            self.optimizer.zero_grad()

            print("-----"*10)
            print("VP Training Phase")
            print("-----"*10)
            num_batches = len(train_dataloader)
            for batch_number, (rgb_img, obj_mask ,vp) in enumerate(train_dataloader):
                print("Training Batch: " + str(batch_number) + " / " + str(num_batches))
                rgb_img = rgb_img.type(torch.FloatTensor)

                #Need for loss comp.
                obj_mask = obj_mask.type(torch.FloatTensor)
                obj_mask = obj_mask.to(device=self.device)

                #Need for loss comp.
                vp = vp.type(torch.FloatTensor)
                vp = vp.to(device=self.device)

                outputs = self.model(rgb_img)
                obj_mask_pred = outputs[0]
                obj_mask_pred = obj_mask_pred.to(device=self.device)
                vp_pred = outputs[1]
                vp_pred = vp_pred.to(device=self.device)
                loss_vp = self.loss_vp(vp_pred.view(vp.shape), vp)


                #CHECK THIS BELOW!!!!
                loss_vp.backward()
                self.optimizer.step()

                #Updating training accuracy and training loss
                train_loss += loss_vp.item()
                #Using PIXEL-Wise Accuracy!
                vp_pred = vp_pred.view(vp.shape)
                train_vp_acc += ((vp_pred == vp).sum().item() )  / (vp.size(0) * vp.size(1) * vp.size(2))

                self.optimizer.zero_grad()

            #Normalizing by number of batches
            train_loss = train_loss /  num_batches
            train_vp_acc = train_vp_acc / num_batches

            validation_loss, validation_acc = self.eval(validation_dataloader)
            elapsed = time.time() - start_time
            print(
                "Validation Training: Epoch {:d} Train loss: {:.2f}. Train Accuracy: {:.2f}. Validation loss: {:.2f}. Validation Accuracy: {:.2f}. Elapsed time: {:.2f}ms. \n".format(
                e + 1, train_loss, train_vp_acc, validation_loss, validation_acc, elapsed)
                )

        
        for e in range(num_epochs_general):
            start_time = time.time()
            train_loss = 0
            train_acc_vp_p2 = 0.0
            train_acc_obj = 0.0
            w1 = 1
            w4 = w1

            self.optimizer.zero_grad()
            print("----"*10)
            print("Complete Net Training Phase (Phase II)")
            print("----"*10)
            for batch_number, (rgb_img, obj_mask, vp) in enumerate(train_dataloader):
                print("Training Batch: " + str(batch_number) + " / " + str(num_batches))
                rgb_img = rgb_img.type(torch.FloatTensor)
                rgb_img = rgb_img.to(device=self.device)

                obj_mask = obj_mask.type(torch.FloatTensor)
                obj_mask = obj_mask.to(device=self.device)

                vp = vp.type(torch.FloatTensor)
                vp = vp.to(device=self.device)

                outputs = self.model(rgb_img)
                obj_mask_pred = outputs[0]
                obj_mask_pred = obj_mask_pred.to(device=self.device)
                vp_pred = outputs[1]
                vp_pred = vp_pred.to(device=self.device)

                loss_vp = self.loss_vp(vp_pred.view(vp.shape), vp)
                loss_obj_mask = self.loss_obj_mask(obj_mask_pred.view(obj_mask.shape),obj_mask)
                if(batch_number == 0):
                    w1 = 1 / loss_obj_mask
                    w4 = 1 / loss_vp

                loss = w1*loss_obj_mask + w4*loss_vp
                loss.backward()
                self.optimizer.step()
                train_loss+= loss.item()

                vp_pred = vp_pred.view(vp.shape)
                obj_mask_pred = obj_mask_pred.view(obj_mask.shape)


                train_acc_vp_p2 += ((vp_pred == vp).sum().item() )  / (vp.size(0) * vp.size(1) * vp.size(2))
                train_acc_obj += ((obj_mask_pred == obj_mask).sum().item() )  / (obj_mask.size(0) * obj_mask.size(1) * obj_mask.size(2))
                self.optimizer.zero_grad()

            #Normalizing by number of batches
            train_loss = train_loss /  num_batches
            train_acc_vp_p2 = train_acc_vp_p2 / num_batches
            train_acc_obj = train_acc_obj / num_batches

            validation_loss, validation_acc = self.eval(validation_dataloader)
            elapsed = time.time() - start_time
            print(
                "General Training: Epoch {:d} Train loss: {:.2f}. Train Accuracy Obj Mask: {:.2f}. Train Accuracy VP: {:.2f}. Validation loss: {:.2f}. Validation Accuracy: {:.2f}. Elapsed time: {:.2f}ms. \n".format(
                e + 1, train_loss, train_acc_obj, train_acc_vp_p2, validation_loss, validation_acc, elapsed)
                )
    
    
    def eval(self, 
            dataloader: DataLoader):
        
        """
        Args:
            Dataloader: A torch dataloader
        
        Note: This function evaluates the model on the dataloader and returns obj_mask_loss, vp_loss, obj_mask_acc, vp_acc

        """
        self.model.eval()
        with torch.no_grad():
            obj_mask_loss = 0
            vp_loss = 0
            vp_acc = 0.0
            obj_mask_acc = 0.0

            num_batches = len(dataloader)
            for batch_number, (rgb_img,obj_mask, vp) in enumerate(dataloader):
                print("Eval Batch: " + str(batch_number) + " / " + str(num_batches))
                rgb_img = rgb_img.type(torch.FloatTensor)
                rgb_img = rgb_img.to(device=self.device)

                obj_mask = obj_mask.type(torch.FloatTensor)
                obj_mask = obj_mask.to(device=self.device)

                vp = vp.type(torch.FloatTensor)
                vp = vp.to(device=self.device)

                outputs = self.model(rgb_img)
                obj_mask_pred = outputs[0]
                obj_mask_pred = obj_mask_pred.to(device=self.device)
                vp_pred = outputs[1]
                vp_pred = vp_pred.to(device=self.device)

                loss_vp = self.loss_vp(vp_pred.view(vp.shape), vp)
                loss_obj_mask = self.loss_obj_mask(obj_mask_pred.view(obj_mask.shape),obj_mask)

                vp_loss += loss_vp.item()
                obj_mask_loss += loss_obj_mask.item()

                obj_mask_pred = obj_mask_pred.view(obj_mask.shape)
                vp_pred = vp_pred.view(vp.shape)

                vp_acc += ((vp_pred == vp).sum().item() )  / (vp.size(0) * vp.size(1) * vp.size(2))
                obj_mask_acc += ((obj_mask_pred == obj_mask).sum().item() )  / (obj_mask.size(0) * obj_mask.size(1) * obj_mask.size(2))

                obj_mask_loss += loss_obj_mask
                vp_loss += loss_vp

        obj_mask_loss = obj_mask_loss / num_batches
        vp_loss = vp_loss / num_batches

        vp_acc = vp_acc / num_batches
        obj_mask_acc = obj_mask_acc / num_batches

        return obj_mask_loss, vp_loss , obj_mask_acc, vp_acc


    #TODO: Update test function to get test set predictions (Currently very naive)
    def test(self, dataloader: DataLoader):
        """
        Args:
            Dataloader: A torch dataloader
        
        Note: This function returns list of prediction of obj_maskmasks on testset

        """

        self.model.eval()
        with torch.no_grad():
            for batch_number, (rgb_img, img_name) in tqdm(enumerate(dataloader)):
                rgb_img = rgb_img.to(device = self.device)
                obj_mask_pred, vp_pred = torch.round(self.model(rgb_img))
                obj_mask_pred = obj_mask_pred.numpy()
                vp_pred = vp_pred.numpy()
                temp_dict = {'obj_mask_pred': obj_mask_pred, 'vp_pred':vp_pred}
                scipy.io.savemat(os.getcwd() + "/test_pred/" + img_name + "_pred", temp_dict)

        print("Done Testing!")
        
        return

