#!/usr/bin/python
# -*- coding: utf-8 -*-

""" Cressot Loic
    ISIR - CNRS / Sorbonne Université
    10/2018
""" 

"""
    main : main script for computing states from observations and learn policies with fitted q iteration

    This script trains and computes states representations from image observations, rewards and actions,
    using the Jonschkowski and Brock method from 2015 paper 'Learning State Representations with Robotic Priors'
    You can test the learned representation in RL with our q fitted iteration implementation, as in the paper
"""

# System
import os, warnings, argparse
import random, time

# maths
import numpy as np
from sklearn.decomposition import PCA

# plotting
import matplotlib.pyplot as plt

# repo
import tools
import jonschkowski_priors


warnings.filterwarnings('ignore') # ignore warnings



parser = argparse.ArgumentParser(description=None)

required = parser.add_argument_group('Required arguments')
required.add_argument('-trd','--training_data', default='', help='Select training data file to load', required=True)

parser.add_argument('-ted','--test_data', default='', help='Select testing data file to load')
parser.add_argument('-ql','--qlearning',  action='store_true', default=False, help='Perform Q-learning state evaluation')
parser.add_argument('-r','--recordto', default='', help='Select a file for recording computed states')
parser.add_argument('-ne','--num_epochs', type=int, default=25, help='Number of training epochs')
parser.add_argument('-lr','--learning_rate', type=float, default=1e-4, help='Number of training epochs')
parser.add_argument('-reg','--l1_reg', type=float, default=1e-3, help='l1 regularizer')
parser.add_argument('-sd','--state_dim', type=int, default=2, help='State dimensions')
parser.add_argument('-vr','--validation_ratio', type=float, default=0.1, help='Ratio of validation data split from training data')
parser.add_argument('-bs','--batch_size', type=int, default=256, help='Batch size')
parser.add_argument('-rs','--seed', type=int, default=None, help='Seed for random')
parser.add_argument('-tu','--tanh_units', type=int, default=None, help='hidden tanh units, default is None (linear model)')
parser.add_argument('-w','--weights', nargs=4, type=float, metavar=('wt','wp','wc','wr'), default=(1.0,5.0,1.0,5.0), help='Weights of loss components')
parser.add_argument('-dis','--display', action='store_true', default=False, help='display plots')
parser.add_argument('-vis','--visible_train', action='store_true', default=False, help='Set the RL to visible')
parser.add_argument('-v','--verbose', action='store_true', default=False, help='Verbose')

args = parser.parse_args()

if args.recordto and args.recordto[-1]!='/':
    args.recordto = args.recordto+'/'

if args.recordto:
    os.makedirs(args.recordto, exist_ok=True)

if not (args.recordto or args.display) :
    raise Exception('\nPlease either record (-r) or display (-dis) results ! (or both) \n') 

if args.qlearning and not args.recordto :
    raise Exception('\nPlease give a record folder (-r) for saving results of qlearning \n')

if args.validation_ratio <= 0.0 or args.validation_ratio >= 1.0:
    raise ValueError('Wrong validation_ratio parameter, must be in range ]0,1[ ') 

# init seed (with np.random, not random) before creating anything with keras, this allows to debug with deterministic seed in args.seed
np.random.seed(args.seed if args.seed else int(time.time()) )


# load data
training_data = tools.load_data(args.training_data)      
# create a model implementing the paper method
jp_model = jonschkowski_priors.Priors_model(
                        obs_shape = list(training_data['observations'][0].shape), 
                        state_dim = args.state_dim,
                        learning_rate=args.learning_rate, 
                        l1_reg = args.l1_reg, 
                        loss_weights=args.weights,
                        noise_stddev=1e-6,
                        tanh_units = args.tanh_units
                       )

# if args.qlearning is False, then run a simple learning and plotting of the representations
#      you can also specify a test dataset to test the learned representation afterward
if not args.qlearning:
    # learn the model directly for every iterations
    states ,history = tools.learn_states(training_data=training_data,
                                    model = jp_model,                                      
                                    num_epochs=args.num_epochs,
                                    batch_size = args.batch_size,
                                    recordto=args.recordto,
                                    display=args.display,
                                    validation_ratio = args.validation_ratio,
                                    )

    # record the vaildation loss history
    temporalcoherence_loss_record = history.history['val_t_loss']
    proportionality_loss_record = history.history['val_p_loss']
    causality_loss_record = history.history['val_c_loss']
    repeatability_loss_record = history.history['val_r_loss']

    if args.test_data:
        tools.compute_states( test_data=args.test_data,
                            model=jp_model,
                            recordto=args.recordto,
                            display=args.display,
                          )

# else, we will run the qlearning experiment of the paper :
#   after each learning iteration, we run 10 q fitted iteration learnings
#       for each q learning, we test it on 20 episodes of 25 steps and average the sum of rewards
#   plot representations every 5 learnings and average reward over each 20
else:

    import fqiteration as fqi
    import gym_env.agent as agent
    import gym_env.policy as policy
    import gym_env.run_round_bot as run_round_bot

    # gym round bot
    from gym_round_bot.envs import round_bot_controller

    # those are the argument parameters used for setting the gym environment where we got the training data
    # we can use these arguments to test a learned policy in this same environment
    env_args = training_data['args'].item(0)
    # integer version of the actions
    actions_int = training_data['actions_int'].item(0)
    n_actions = training_data['num_actions'] # number of actions

    n_qlearnings = 10 # as in the paper, the number of different q iteration learnings
    n_test_episodes = 20 # as in the paper, the number of episodes to test the learned policy
    n_test_steps = 25 # as in the paper, the number of steps per env policy test iteration
    n_rbf = 100 # as in the paper, the number of rbf kernels used in q fitted iteration

    # create contained array to save all test performances :
    #   array size : args.num_epochs learning steps X 10 q learnings X 20 test episodes X 25 steps per episode
    test_performance = np.zeros([args.num_epochs, n_qlearnings, n_test_episodes, n_test_steps])

    ### create the gym environment for testing the learned policies (the same as the training_data env)
    # the controller
    controller=round_bot_controller.make(name=env_args['controller'],
                                speed=env_args['speed'],
                                dtheta=env_args['dtheta'],
                                fixed_point=list(env_args['fixed_point']),
                                xzrange=env_args['xztrange'][0:2],
                                thetarange=env_args['xztrange'][2],
                                noise_ratio=env_args['noise_ratio'],
                                int_actions=True)

    # create a function for computing states form the observations given by the env
    obs2states = lambda X: jp_model.phi(X) # centering and scaling are done inside phi

    # also retrieve global point of view parameter
    if env_args['auto_global_pov']:
        env_args['global_pov'] = True
    
    if env_args['global_pov']!=True:
        global_pov = (0.0,env_args['global_pov'],0.0) if env_args['global_pov'] and env_args['global_pov']!=0.0 else None
    else:
        global_pov = True

    # finally the env itself
    env = run_round_bot.make_round_bot_env(
            world={'name':env_args['world_name'], 'size':env_args['world_size']},
            texture=env_args['texture'],
            obssize=env_args['obssize'],
            winsize=[200,200] if args.visible_train else None,
            controller=controller,
            global_pov=global_pov,
            visible=args.visible_train,
            perspective = not env_args['orthogonal'],
            multiview=env_args['multiview'],
            focal=env_args['focal'],
            max_step=n_test_steps,
            random_start= True,
            distractors = env_args['distractors'],
            observation_transformation = obs2states,
            )


    ### learning iteration loop

    # record loss for plotting
    temporalcoherence_loss_record = np.zeros(args.num_epochs)
    proportionality_loss_record = np.zeros(args.num_epochs)
    causality_loss_record = np.zeros(args.num_epochs)
    repeatability_loss_record = np.zeros(args.num_epochs)

    for learning_epoch in range(args.num_epochs):

        states, history = tools.learn_states(
                            training_data=training_data,
                            model = jp_model,                                      
                            num_epochs=1,
                            batch_size = args.batch_size,
                            recordto='',
                            display=args.display,
                            validation_ratio = args.validation_ratio,
                        ) 

        # record the validation loss history
        temporalcoherence_loss_record[learning_epoch] = history.history['val_t_loss'][0]
        proportionality_loss_record[learning_epoch] = history.history['val_p_loss'][0]
        causality_loss_record[learning_epoch] = history.history['val_c_loss'][0]
        repeatability_loss_record[learning_epoch] = history.history['val_r_loss'][0]

        # plot representations every learning
        if learning_epoch==0 or (learning_epoch+1)%5 == 0:
            tools.plot_representation(
                states[1:],
                # offset reward of 1 to match observations, and don't show previous rewards for episode_start steps
                training_data['rewards'][:-1]*(training_data['episode_starts'][1:]==False),
                name='Observation-State-Mapping for ' + str(learning_epoch+1) + 'learning epoch',
                add_colorbar=True, 
                state_dim=min(jp_model.state_dim,3),
                plot_name='_train_'+str(learning_epoch+1),
                recordto=args.recordto,
                display=False,
                )


        ### qlearning loop
        for q_learning in range(n_qlearnings):

            # Perform fitted Q iterations and get states policy
            qit = fqi.Fitted_QIteration(n_rbf=n_rbf, n_actions=n_actions)
            # train a policy with q fitted iteration using an integer representation of the actions 'actions_int'
            state_policy = qit.fit_sk( states, actions_int, training_data['rewards'], 0.9, 10, recompute_mapping=True)
            # plug this policy into our policy class module
            state_policy = policy.Plug_policy(state_policy, env.controller.action_space_int)
            # create an agent with this policy
            rb_agent = agent.RoundBotAgent(state_policy)
            # test the agent in the env
            stats = rb_agent.run_in_env(env, n_test_episodes, seed=None) # 20 episodes as in the paper
            # record all episodes rewards for this evaluation run and this model and this learning
            test_performance[learning_epoch, q_learning, :,:] = np.reshape(np.array(stats['rewards']),[n_test_episodes, n_test_steps])            

            if args.verbose:
                print( 'Q fitted iteration test number : '+ str(q_learning) +'. Mean reward over'+ str(n_test_episodes)+' episodes : ' +\
                    str( np.mean( stats['reward_ep'].flatten() ) )+' \n' )


### PLOTTING 

## LOSSES

# divide by the weight to have the unweighted loss value
causality_loss_record = np.array( causality_loss_record )/args.weights[2]
repeatability_loss_record = np.array( repeatability_loss_record )/args.weights[3]
proportionality_loss_record = np.array( proportionality_loss_record )/args.weights[1]
temporalcoherence_loss_record = np.array( temporalcoherence_loss_record )/args.weights[0]

# plot the stacked losses' histories
figloss=plt.figure('Loss')

axes = plt.gca()
axes.set_ylim([0,None])

plt.plot(np.arange(1,args.num_epochs+1), temporalcoherence_loss_record + proportionality_loss_record + repeatability_loss_record + causality_loss_record)
plt.plot(np.arange(1,args.num_epochs+1), proportionality_loss_record + repeatability_loss_record + causality_loss_record)
plt.plot(np.arange(1,args.num_epochs+1), repeatability_loss_record + causality_loss_record)
plt.plot(np.arange(1,args.num_epochs+1), causality_loss_record)

plt.title('Model loss')    
plt.ylabel('Loss (stacked)')
plt.xlabel('Epoch')
plt.legend(['temporalcoherence_loss','proportionality_loss','repeatability_loss','causality_loss'], loc='upper right')

if args.display: 
    plt.show()

if args.recordto:
    plot_name = 'loss_history' if not args.qlearning else 'loss_history_ql'
    figloss.savefig(args.recordto+plot_name+'.png')# save the figure to file   



## PCA VARIANCE RATIO 

pca = PCA(n_components=states.shape[1])
pca.fit_transform(states)

figpca = plt.figure('PCA')
plt.bar( np.arange(1,states.shape[1]+1), pca.explained_variance_ratio_ )
plt.title('PCA variance')    
plt.ylabel('Normalized eigenvalue')
plt.xlabel('Principal component')

if args.display: 
    plt.show()

if args.recordto:
    figpca.savefig(args.recordto+'PCA_variance.png')# save the figure to file   



## Q LEARNING

if args.qlearning :
    # plot the average sum of rewards
    figrewards=plt.figure('rewards')
    axes.set_ylim([0,None])
    plt.scatter( np.repeat(np.arange(1,args.num_epochs+1), n_qlearnings), np.mean( np.sum( test_performance[:,], axis=3), axis=2).flatten()  )

    plt.title('Q fitted iteration performance')    
    plt.ylabel('Average sum of rewards')
    plt.xlabel('Epoch')

    if args.display : 
        plt.show()

    if args.recordto:
        figrewards.savefig(args.recordto+'ql_rewards.png')# save the figure to file   


if args.display :
    input('Press any key to exit plotting')


