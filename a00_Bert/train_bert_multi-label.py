# coding=utf-8
"""
train bert model
"""
import bert_modeling as modeling
import tensorflow as tf
import numpy as np

from utils import load_data,init_label_dict,get_label_using_logits,get_target_label_short,compute_confuse_matrix,\
    compute_micro_macro,compute_confuse_matrix_batch,get_label_using_logits_batch,get_target_label_short_batch

FLAGS=tf.app.flags.FLAGS
tf.app.flags.DEFINE_string("cache_file_h5py","../data/ieee_zhihu_cup/data.h5","path of training/validation/test data.") #../data/sample_multiple_label.txt
tf.app.flags.DEFINE_string("cache_file_pickle","../data/ieee_zhihu_cup/vocab_label.pik","path of vocabulary and label files") #../data/sample_multiple_label.txt

tf.app.flags.DEFINE_float("learning_rate",0.0003,"learning rate")
tf.app.flags.DEFINE_integer("batch_size", 4, "Batch size for training/evaluating.") #批处理的大小 32-->128
tf.app.flags.DEFINE_integer("decay_steps", 1000, "how many steps before decay learning rate.") #6000批处理的大小 32-->128
tf.app.flags.DEFINE_float("decay_rate", 1.0, "Rate of decay for learning rate.") #0.65一次衰减多少
tf.app.flags.DEFINE_string("ckpt_dir","checkpoint/","checkpoint location for the model")
tf.app.flags.DEFINE_boolean("is_training",True,"is training.true:tranining,false:testing/inference")
tf.app.flags.DEFINE_integer("num_epochs",10,"number of epochs to run.")
tf.app.flags.DEFINE_integer("validate_every", 1, "Validate every validate_every epochs.") #每10轮做一次验证
tf.app.flags.DEFINE_boolean("use_pretrain_embedding",False,"whether to use embedding or not.")
tf.app.flags.DEFINE_string("word2vec_model_path","","word2vec's vocabulary and vectors")
# below hyper-parameter is for bert model
tf.app.flags.DEFINE_integer("hidden_size",768,"hidden size")
tf.app.flags.DEFINE_integer("num_hidden_layers",12,"number of hidden layers")
tf.app.flags.DEFINE_integer("num_attention_heads",12,"number of attention headers")
tf.app.flags.DEFINE_integer("intermediate_size",3072,"intermediate size of hidden layer")
tf.app.flags.DEFINE_integer("max_seq_length",200,"max sequence length")


def main(_):
    # 1.get training data and vocabulary & labels dict
    word2index, label2index, trainX, trainY, vaildX, vaildY, testX, testY = load_data(FLAGS.cache_file_h5py,FLAGS.cache_file_pickle)
    vocab_size = len(word2index); print("bert model.vocab_size:", vocab_size);
    num_labels = len(label2index); print("num_labels:", num_labels)
    num_examples, FLAGS.max_seq_length = trainX.shape;print("num_examples of training:", num_examples, ";max_seq_length:", FLAGS.max_seq_length)

    # 2. create model
    bert_config = modeling.BertConfig(vocab_size=len(word2index), hidden_size=FLAGS.hidden_size, num_hidden_layers=FLAGS.num_hidden_layers,
                                      num_attention_heads=FLAGS.num_attention_heads,intermediate_size=FLAGS.intermediate_size)
    input_ids = tf.placeholder(tf.int32, [FLAGS.batch_size, FLAGS.max_seq_length], name="input_ids")
    input_mask = tf.placeholder(tf.int32, [FLAGS.batch_size, FLAGS.max_seq_length], name="input_mask")
    segment_ids = tf.placeholder(tf.int32, [FLAGS.batch_size,FLAGS.max_seq_length],name="segment_ids")
    label_ids = tf.placeholder(tf.float32, [FLAGS.batch_size,num_labels], name="label_ids")
    is_training = FLAGS.is_training #tf.placeholder(tf.bool, name="is_training")

    use_one_hot_embeddings = False

    loss, per_example_loss, logits, probabilities, model = create_model(bert_config, is_training, input_ids, input_mask,
                                                            segment_ids, label_ids, num_labels,use_one_hot_embeddings)

    # 3. train the model by calling create model, get loss
    gpu_config = tf.ConfigProto()
    gpu_config.gpu_options.allow_growth = True
    sess = tf.Session(config=gpu_config)
    sess.run(tf.global_variables_initializer())
    number_of_training_data = len(trainX)
    iteration = 0
    curr_epoch = 0 #sess.run(textCNN.epoch_step)
    batch_size = FLAGS.batch_size
    saver = tf.train.Saver()
    for epoch in range(curr_epoch, FLAGS.num_epochs):
        loss_total, counter = 0.0, 0
        for start, end in zip(range(0, number_of_training_data, batch_size),range(batch_size, number_of_training_data, batch_size)):
            iteration = iteration + 1
            input_mask_,segment_ids_=get_input_mask_segment_ids(trainX[start:end])
            feed_dict = {input_ids: trainX[start:end], input_mask: input_mask_, segment_ids:segment_ids_,
                         label_ids:trainY[start:end]}
            curr_loss = sess.run(loss, feed_dict) # todo
            loss_total, counter = loss_total + curr_loss, counter + 1
            if counter % 50 == 0:
                print(epoch,"\t",iteration,"\tloss:",loss_total/float(counter),"\tcurrent_loss:",curr_loss)

            # evaulation
            if start % (3000 * FLAGS.batch_size) == 0:
                eval_loss, f1_score, f1_micro, f1_macro = do_eval(sess,input_ids,input_mask,segment_ids,label_ids,is_training,loss,
                                                                  probabilities,vaildX, vaildY, num_labels,batch_size)
                print("Epoch %d Validation Loss:%.3f\tF1 Score:%.3f\tF1_micro:%.3f\tF1_macro:%.3f" % (
                    epoch, eval_loss, f1_score, f1_micro, f1_macro))
                # save model to checkpoint
                save_path = FLAGS.ckpt_dir + "model.ckpt"
                print("Going to save model..")
                saver.save(sess, save_path, global_step=epoch)
    # 3. eval the model from time to time

def do_eval(sess,input_ids,input_mask,segment_ids,label_ids,is_training,loss,probabilities,vaildX, vaildY, num_labels,batch_size):
    vaildX = vaildX[0:3000]
    vaildY = vaildY[0:3000]
    number_examples = len(vaildX)
    eval_loss, eval_counter, eval_f1_score, eval_p, eval_r = 0.0, 0, 0.0, 0.0, 0.0
    label_dict = init_label_dict(num_labels)
    for start, end in zip(range(0, number_examples, batch_size), range(batch_size, number_examples, batch_size)):
        input_mask_, segment_ids_ = get_input_mask_segment_ids(vaildX[start:end])
        feed_dict = {input_ids: vaildX[start:end],input_mask:input_mask_,segment_ids:segment_ids_,
                     label_ids:vaildY[start:end]}
        curr_eval_loss, prob = sess.run([loss, probabilities],feed_dict)
        target_labels=get_target_label_short_batch(vaildY[start:end])
        predict_labels=get_label_using_logits_batch(prob)
        label_dict=compute_confuse_matrix_batch(target_labels,predict_labels,label_dict,name='bert')
        eval_loss, eval_counter = eval_loss + curr_eval_loss, eval_counter + 1

    f1_micro, f1_macro = compute_micro_macro(label_dict)  # label_dictis a dict, key is: accusation,value is: (TP,FP,FN). where TP is number of True Positive
    f1_score = (f1_micro + f1_macro) / 2.0
    return eval_loss / float(eval_counter), f1_score, f1_micro, f1_macro

def bert_predict_fn():
    # 1. predict based on
    pass

def create_model(bert_config, is_training, input_ids, input_mask, segment_ids,labels, num_labels, use_one_hot_embeddings):
  """Creates a classification model."""
  model = modeling.BertModel(
      config=bert_config,
      is_training=is_training,
      input_ids=input_ids,
      input_mask=input_mask,
      token_type_ids=segment_ids,
      use_one_hot_embeddings=use_one_hot_embeddings)

  output_layer = model.get_pooled_output()
  hidden_size = output_layer.shape[-1].value
  output_weights = tf.get_variable("output_weights", [num_labels, hidden_size],initializer=tf.truncated_normal_initializer(stddev=0.02))
  output_bias = tf.get_variable("output_bias", [num_labels], initializer=tf.zeros_initializer())

  with tf.variable_scope("loss"):
    if is_training:  # if training, add dropout
      output_layer = tf.nn.dropout(output_layer, keep_prob=0.9)
    logits = tf.matmul(output_layer, output_weights, transpose_b=True)
    print("output_layer:",output_layer.shape,";output_weights:",output_weights.shape,";logits:",logits.shape)

    logits = tf.nn.bias_add(logits, output_bias)
    probabilities = tf.nn.softmax(logits, axis=-1)
    per_example_loss=tf.nn.sigmoid_cross_entropy_with_logits(labels=labels, logits=logits)
    loss = tf.reduce_mean(per_example_loss)

    return loss, per_example_loss, logits, probabilities,model

def get_input_mask_segment_ids(train_x_batch):
    """
    get input mask and segment ids given a batch of input x.
    if sequence length of input x is max_sequence_length, then shape of both input_mask and segment_ids should be
    [batch_size, max_sequence_length]
    :param train_x_batch:
    :return: input_mask_,segment_ids
    """
    batch_size,max_sequence_length=train_x_batch.shape
    input_mask=np.ones((batch_size,max_sequence_length),dtype=np.int32)
    for i in range(batch_size):
        input_x_=train_x_batch[i] # a list, length is max_sequence_length
        input_x=list(input_x_)
        for j in range(len(input_x)):
            if input_x[j]==0:
                input_mask[i][j:]=0
                break
    segment_ids=np.ones((batch_size,max_sequence_length),dtype=np.int32)
    return input_mask, segment_ids

# tested.
#train_x_batch=np.ones((5,6))
#train_x_batch[0,5]=0
#train_x_batch[1,5]=0
#train_x_batch[1,4]=0
#print("train_x_batch:",train_x_batch)
#input_mask, segment_ids=get_input_mask_segment_ids(train_x_batch)
#print("input_mask:",input_mask)
#print("segment_ids:",segment_ids)

if __name__ == "__main__":
    tf.app.run()