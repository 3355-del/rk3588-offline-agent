// Host-only SDK fixture tests of buffer/layout/error handling. Not NPU validation.
#include "image_enc.h"
#include <cassert>
#include <cstring>
#include <iostream>
static bool fail_mask=false,bad_shape=false,short_output=false;
static unsigned destroyed=0,released=0;
static float data0[]={1,2,3,4},data1[]={5,6,7,8};
extern "C" {
int rknn_init(rknn_context* c,void*,uint32_t,uint32_t,rknn_init_extend*){*c=1;return 0;}
int rknn_destroy(rknn_context){++destroyed;return 0;}
int rknn_set_core_mask(rknn_context,rknn_core_mask){return fail_mask?-1:0;}
int rknn_query(rknn_context,rknn_query_cmd cmd,void* info,uint32_t){
    if(cmd==RKNN_QUERY_IN_OUT_NUM){auto* n=static_cast<rknn_input_output_num*>(info);n->n_input=1;n->n_output=2;return 0;}
    auto* a=static_cast<rknn_tensor_attr*>(info);
    if(cmd==RKNN_QUERY_INPUT_ATTR){a->n_dims=4;a->dims[0]=1;a->dims[1]=3;a->dims[2]=2;a->dims[3]=2;a->fmt=RKNN_TENSOR_NCHW;}
    else {a->n_dims=3;a->dims[0]=1;a->dims[1]=2;a->dims[2]=bad_shape?0:2;a->n_elems=4;}
    return 0;
}
int rknn_inputs_set(rknn_context,uint32_t n,rknn_input in[]){assert(n==1&&in[0].size==12&&in[0].fmt==RKNN_TENSOR_NHWC);return 0;}
int rknn_run(rknn_context,rknn_run_extend*){return 0;}
int rknn_outputs_get(rknn_context,uint32_t n,rknn_output out[],rknn_output_extend*){
    assert(n==2&&out[0].want_float&&out[1].index==1);out[0].buf=data0;out[1].buf=data1;out[0].size=short_output?1:sizeof(data0);out[1].size=sizeof(data1);return 0;
}
int rknn_outputs_release(rknn_context,uint32_t n,rknn_output[]){released=n;return 0;}
}
int main(){
    rknn_app_context_t a{};unsigned char pixels[12]{};float output[8]{};
    assert(init_imgenc("fixture",&a,3)==0);assert(a.model_image_token==2&&a.model_embed_size==2);
    assert(run_imgenc(&a,pixels,output)==0);float expected[]={1,2,5,6,3,4,7,8};assert(std::memcmp(output,expected,sizeof(output))==0&&released==2);
    short_output=true;released=0;assert(run_imgenc(&a,pixels,output)<0&&released==2);release_imgenc(&a);assert(a.rknn_ctx==0);
    fail_mask=true;auto prior=destroyed;assert(init_imgenc("fixture",&a,3)<0&&destroyed==prior+1&&a.rknn_ctx==0);
    fail_mask=false;bad_shape=true;assert(init_imgenc("fixture",&a,3)<0&&a.output_attrs==nullptr);
    std::cout<<"PASS: encoder shape, interleaving, full release and init failure cleanup (SDK fixture only)\n";
}
