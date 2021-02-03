	#!/usr/bin/env python3

	# Reference 1 : https://github.com/pytorch/examples
	# Reference 3 : https://arxiv.org/pdf/1511.06434.pdf
	# Reference 4 : https://arxiv.org/pdf/1701.07875.pdf
	# Reference 5 : https://github.com/martinarjovsky/WassersteinGAN
	# Reference 6 : https://github.com/caogang/wgan-gp
	# To get TensorBoard output, use the python command: tensorboard --logdir /home/alexia/Output/WGAN-GP

	## Parameters
if __name__ == '__main__':
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument('--image_size', type=int, default=64)
	parser.add_argument('--batch_size', type=int, default=64)
	parser.add_argument('--n_colors', type=int, default=3)
	parser.add_argument('--z_size', type=int, default=100) # DCGAN paper original value
	parser.add_argument('--G_h_size', type=int, default=128, help='Number of hidden nodes in the Generator. Too small leads to bad results, too big blows up the GPU RAM.') # DCGAN paper original value
	parser.add_argument('--D_h_size', type=int, default=128, help='Number of hidden nodes in the Discriminator. Too small leads to bad results, too big blows up the GPU RAM.') # DCGAN paper original value
	parser.add_argument('--lr_D', type=float, default=.0001, help='Discriminator learning rate') # WGAN original value
	parser.add_argument('--lr_G', type=float, default=.0001, help='Generator learning rate')
	parser.add_argument('--n_iter', type=int, default=100000, help='Number of iterations')
	parser.add_argument('--n_critic', type=int, default=5, help='Number of training with D before training G') # WGAN original value
	parser.add_argument('--beta1', type=float, default=0, help='Adam betas[0], WGAN-GP paper recommends 0') # WGAN original value
	parser.add_argument('--beta2', type=float, default=.9, help='Adam betas[1], WGAN-GP paper recommends .90') # WGAN original value
	parser.add_argument('--penalty', type=float, default=10, help='Gradient penalty parameter for WGAN-GP')
	parser.add_argument('--SELU', type=bool, default=False, help='Using scaled exponential linear units (SELU) which are self-normalizing instead of ReLU with BatchNorm. This improves stability.')
	parser.add_argument('--seed', type=int)
	parser.add_argument('--input_folder', default='./images', help='input folder')
	parser.add_argument('--output_folder', default='./output', help='output folder')
	parser.add_argument('--G_load', default='', help='Full path to Generator model to load (ex: /home/output_folder/run-5/models/G_epoch_11.pth)')
	parser.add_argument('--D_load', default='', help='Full path to Discriminator model to load (ex: /home/output_folder/run-5/models/D_epoch_11.pth)')
	parser.add_argument('--cuda', type=bool, default=True, help='enables cuda')
	parser.add_argument('--n_gpu', type=int, default=1, help='number of GPUs to use')
	parser.add_argument('--gen_extra_images', type=int, default=0, help='Every 50 generator iterations, generate additional images with "batch_size" random fake cats.')
	param = parser.parse_args()

	## Imports

	# Time
	import time
	start = time.time()

	# Check folder run-i for all i=0,1,... until it finds run-j which does not exists, then creates a new folder run-j
	import os
	run = 0

	base_dir = f"{param.output_folder}/run-{run}"
	while os.path.exists(base_dir):
		run += 1
		base_dir = f"{param.output_folder}/run-{run}"
	os.mkdir(base_dir)
	logs_dir = f"{base_dir}/logs"
	os.mkdir(logs_dir)
	os.mkdir(f"{base_dir}/images")
	os.mkdir(f"{base_dir}/models")
	if param.gen_extra_images > 0:
		os.mkdir(f"{base_dir}/images/extra")

	# where we save the output
	log_output = open(f"{logs_dir}/log.txt", 'w')
	print(param)
	print(param, file=log_output)

	import numpy
	import torch
	import torch.autograd as autograd
	from torch.autograd import Variable

	# For plotting the Loss of D and G using tensorboard
	from tensorboard_logger import configure, log_value
	configure(logs_dir, flush_secs=5)

	import torchvision
	import torchvision.datasets as dset
	import torchvision.transforms as transf
	import torchvision.models as models
	import torchvision.utils as vutils

	if param.cuda:
		import torch.backends.cudnn as cudnn
		cudnn.benchmark = True

	# To see images
	from IPython.display import Image
	to_img = transf.ToPILImage()

	## Setting seed
	import random
	if param.seed is None:
		param.seed = random.randint(1, 10000)
	print("Random Seed: ", param.seed)
	print("Random Seed: ", param.seed, file=log_output)
	random.seed(param.seed)
	torch.manual_seed(param.seed)
	if param.cuda:
		torch.cuda.manual_seed_all(param.seed)

	## Transforming images
	trans = transf.Compose([
		transf.Scale((param.image_size, param.image_size)),
		# This makes it into [0,1]
		transf.ToTensor(),
		# This makes it into [-1,1] so tanh will work properly
		transf.Normalize(mean = [0.5, 0.5, 0.5], std = [0.5, 0.5, 0.5])
	])

	## Importing dataset
	data = dset.ImageFolder(root=param.input_folder, transform=trans)

	# Generate a random sample
	def generate_random_sample():
		while True:
			random_indexes = numpy.random.choice(data.__len__(), size=param.batch_size, replace=False)
			batch = [data[i][0] for i in random_indexes]
			yield torch.stack(batch, 0)
	random_sample = generate_random_sample()

	## Models
	# The number of layers is implicitly determined by the image size
	# image_size = (4,8,16,32,64, 128, 256, 512, 1024) leads to n_layers = (1, 2, 3, 4, 5, 6, 7, 8, 9)
	# The more layers the bigger the neural get so it's best to decrease G_h_size and D_h_size when the image input is bigger

	# DCGAN generator
	class DCGAN_G(torch.nn.Module):
		def __init__(self):
			super(DCGAN_G, self).__init__()
			main = torch.nn.Sequential()

			# We need to know how many layers we will use at the beginning
			mult = param.image_size // 8

			### Start block
			# Z_size random numbers
			main.add_module('Start-ConvTranspose2d', torch.nn.ConvTranspose2d(param.z_size, param.G_h_size * mult, kernel_size=4, stride=1, padding=0, bias=False))
			if param.SELU:
				main.add_module('Start-SELU', torch.nn.SELU(inplace=True))
			else:
				main.add_module('Start-BatchNorm2d', torch.nn.BatchNorm2d(param.G_h_size * mult))
				main.add_module('Start-ReLU', torch.nn.ReLU())
			# Size = (G_h_size * mult) x 4 x 4

			### Middle block (Done until we reach ? x image_size/2 x image_size/2)
			i = 1
			while mult > 1:
				main.add_module('Middle-ConvTranspose2d [%d]' % i, torch.nn.ConvTranspose2d(param.G_h_size * mult, param.G_h_size * (mult//2), kernel_size=4, stride=2, padding=1, bias=False))
				if param.SELU:
					main.add_module('Middle-SELU [%d]' % i, torch.nn.SELU(inplace=True))
				else:
					main.add_module('Middle-BatchNorm2d [%d]' % i, torch.nn.BatchNorm2d(param.G_h_size * (mult//2)))
					main.add_module('Middle-ReLU [%d]' % i, torch.nn.ReLU())
				# Size = (G_h_size * (mult/(2*i))) x 8 x 8
				mult = mult // 2
				i += 1

			### End block
			# Size = G_h_size x image_size/2 x image_size/2
			main.add_module('End-ConvTranspose2d', torch.nn.ConvTranspose2d(param.G_h_size, param.n_colors, kernel_size=4, stride=2, padding=1, bias=False))
			main.add_module('End-Tanh', torch.nn.Tanh())
			# Size = n_colors x image_size x image_size
			self.main = main

		def forward(self, input):
			if isinstance(input.data, torch.cuda.FloatTensor) and param.n_gpu > 1:
				output = torch.nn.parallel.data_parallel(self.main, input, range(param.n_gpu))
			else:
				output = self.main(input)
			return output

	# DCGAN discriminator (using somewhat the reverse of the generator)
	# Removed Batch Norm we can't backward on the gradients with BatchNorm2d
	class DCGAN_D(torch.nn.Module):
		def __init__(self):
			super(DCGAN_D, self).__init__()
			main = torch.nn.Sequential()

			### Start block
			# Size = n_colors x image_size x image_size
			main.add_module('Start-Conv2d', torch.nn.Conv2d(param.n_colors, param.D_h_size, kernel_size=4, stride=2, padding=1, bias=False))
			if param.SELU:
				main.add_module('Start-SELU', torch.nn.SELU(inplace=True))
			else:
				main.add_module('Start-LeakyReLU', torch.nn.LeakyReLU(0.2, inplace=True))
			image_size_new = param.image_size // 2
			# Size = D_h_size x image_size/2 x image_size/2

			### Middle block (Done until we reach ? x 4 x 4)
			mult = 1
			i = 0
			while image_size_new > 4:
				main.add_module('Middle-Conv2d [%d]' % i, torch.nn.Conv2d(param.D_h_size * mult, param.D_h_size * (2*mult), kernel_size=4, stride=2, padding=1, bias=False))
				if param.SELU:
					main.add_module('Middle-SELU [%d]' % i, torch.nn.SELU(inplace=True))
				else:
					main.add_module('Middle-LeakyReLU [%d]' % i, torch.nn.LeakyReLU(0.2, inplace=True))
				# Size = (D_h_size*(2*i)) x image_size/(2*i) x image_size/(2*i)
				image_size_new = image_size_new // 2
				mult = mult*2
				i += 1

			### End block
			# Size = (D_h_size * mult) x 4 x 4
			main.add_module('End-Conv2d', torch.nn.Conv2d(param.D_h_size * mult, 1, kernel_size=4, stride=1, padding=0, bias=False))
			# Note: No more sigmoid in WGAN, we take the mean now
			# Size = 1 x 1 x 1 (Is a real cat or not?)
			self.main = main

		def forward(self, input):
			if isinstance(input.data, torch.cuda.FloatTensor) and param.n_gpu > 1:
				output = torch.nn.parallel.data_parallel(self.main, input, range(param.n_gpu))
			else:
				output = self.main(input)
			# From batch_size x 1 x 1 (DCGAN used the sigmoid instead before)
			# Convert from batch_size x 1 x 1 to batch_size
			return output.view(-1)

	## Weights init function, DCGAN use 0.02 std
	def weights_init(m):
		classname = m.__class__.__name__
		if classname.find('Conv') != -1:
			m.weight.data.normal_(0.0, 0.02)
		elif classname.find('BatchNorm') != -1:
			# Estimated variance, must be around 1
			m.weight.data.normal_(1.0, 0.02)
			# Estimated mean, must be around 0
			m.bias.data.fill_(0)

	## Initialization
	G = DCGAN_G()
	D = DCGAN_D()

	# Initialize weights
	G.apply(weights_init)
	D.apply(weights_init)

	# Load existing models
	if param.G_load != '':
		G.load_state_dict(torch.load(param.G_load))
	if param.D_load != '':
		D.load_state_dict(torch.load(param.D_load))

	print(G)
	print(G, file=log_output)
	print(D)
	print(D, file=log_output)

	# Soon to be variables
	x = torch.FloatTensor(param.batch_size, param.n_colors, param.image_size, param.image_size)
	# Weighted sum of fake and real image, for gradient penalty
	x_both = torch.FloatTensor(param.batch_size, param.n_colors, param.image_size, param.image_size)
	z = torch.FloatTensor(param.batch_size, param.z_size, 1, 1)
	# Uniform weight
	u = torch.FloatTensor(param.batch_size, 1, 1, 1)
	# This is to see during training, size and values won't change
	z_test = torch.FloatTensor(param.batch_size, param.z_size, 1, 1).normal_(0, 1)
	# For the gradients, we need to specify which one we want and want them all
	grad_outputs = torch.ones(param.batch_size)
	one = torch.FloatTensor([1])
	one_neg = one * -1

	# Everything cuda
	if param.cuda:
		G = G.cuda()
		D = D.cuda()
		x = x.cuda()
		z = z.cuda()
		u = u.cuda()
		z_test = z_test.cuda()
		grad_outputs = grad_outputs.cuda()
		one, one_neg = one.cuda(), one_neg.cuda()

	# Now Variables
	x = Variable(x)
	z = Variable(z)
	z_test = Variable(z_test)

	# Optimizer
	optimizerD = torch.optim.Adam(D.parameters(), lr=param.lr_D, betas=(param.beta1, param.beta2))
	optimizerG = torch.optim.Adam(G.parameters(), lr=param.lr_G, betas=(param.beta1, param.beta2))

	## Fitting model
	for i in range(param.n_iter):

		# Fake images saved
		if i % 50 == 0:
			fake_test = G(z_test)
			vutils.save_image(fake_test.data, '%s/run-%d/images/fake_samples_iter%03d.png' % (param.output_folder, run, i/50), normalize=True)
			for ext in range(param.gen_extra_images):
				z_extra = torch.FloatTensor(param.batch_size, param.z_size, 1, 1).normal_(0, 1)
				if param.cuda:
					z_extra = z_extra.cuda()
				fake_test = G(Variable(z_extra))
				vutils.save_image(fake_test.data, '%s/run-%d/images/extra/fake_samples_iter%03d_extra%01d.png' % (param.output_folder, run, i/50, ext), normalize=True)

		for p in D.parameters():
			p.requires_grad = True

		for t in range(param.n_critic):

			########################
			# (1) Update D network #
			########################

			D.zero_grad()

			# Sample real data
			real_images = random_sample.__next__()
			if param.cuda:
				real_images = real_images.cuda()
			x.data.copy_(real_images)
			# Discriminator Loss real
			errD_real = D(x)
			errD_real = errD_real.mean()
			errD_real.backward(one_neg)

			# Sample fake data
			z.data.normal_(0, 1)
			# Volatile requires less memory and make things sightly faster than detach(), so wy not use it with DCGAN?
			# Simply because we reuse the same fake images, but in WGAN we generate new fake images after training for a while the Discriminator
			z_volatile = Variable(z.data, volatile = True)
			x_fake = Variable(G(z_volatile).data)
			# Discriminator Loss fake
			errD_fake = D(x_fake)
			errD_fake = errD_fake.mean()
			errD_fake.backward(one)

			# Gradient penalty
			u.uniform_(0, 1)
			x_both = x.data*u + x_fake.data*(1-u)
			if param.cuda:
				x_both = x_both.cuda()
			# We only want the gradients with respect to x_both
			x_both = Variable(x_both, requires_grad=True)
			grad = torch.autograd.grad(outputs=D(x_both), inputs=x_both, grad_outputs=grad_outputs, retain_graph=True, create_graph=True, only_inputs=True)[0]
			# We need to norm 3 times (over n_colors x image_size x image_size) to get only a vector of size "batch_size"
			grad_penalty = param.penalty*((grad.norm(2, 1).norm(2,1).norm(2,1) - 1) ** 2).mean()
			grad_penalty.backward()
			# Optimize
			errD_penalty = errD_fake - errD_real + grad_penalty
			errD = errD_fake - errD_real
			optimizerD.step()
			#print("---")
			#print(errD_real)
			#print(errD_fake)
			#print(grad_penalty)

		#########################
		# (2) Update G network: #
		#########################
		for p in D.parameters():
			p.requires_grad = False

		G.zero_grad()

		# Sample fake data
		z.data.normal_(0, 1)
		x_fake = G(z)
		# Generator Loss
		errG = D(x_fake)
		errG = errG.mean()
		#print(errG)
		errG.backward(one_neg)
		optimizerG.step()

		# Log results so we can see them in TensorBoard after
		log_value('errD', errD.item(), i)
		log_value('errD_penalty', errD_penalty.item(), i)
		log_value('errG', errG.item(), i)

		if i % 50 == 0:
			print('[i=%d] W_distance: %.4f W_distance_penalty: %.4f Loss_G: %.4f' % (i, errD.item(), errD_penalty.item(), errG.item()))
			print('[i=%d] W_distance: %.4f W_distance_penalty: %.4f Loss_G: %.4f' % (i, errD.item(), errD_penalty.item(), errG.item()), file=log_output)
		# Save models
		if i % 500 == 0:
			torch.save(G.state_dict(), '%s/run-%d/models/G_%d.pth' % (param.output_folder, run, i))
			torch.save(D.state_dict(), '%s/run-%d/models/D_%d.pth' % (param.output_folder, run, i))
