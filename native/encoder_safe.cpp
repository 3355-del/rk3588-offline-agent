// Based on Rockchip's Apache-2.0 image encoder API; bounded heap buffers and RAII.
#include "image_enc.h"
#include <vector>
#include <cstring>
#include <cstdlib>
#include <limits>
int init_imgenc(const char* path,rknn_app_context_t* a,const int cores) {
    *a={};
    if(rknn_init(&a->rknn_ctx,(void*)path,0,0,nullptr)<0) return -1;
    auto fail=[&](){release_imgenc(a);return -1;};
    auto mask=cores==3?RKNN_NPU_CORE_0_1_2:cores==2?RKNN_NPU_CORE_0_1:RKNN_NPU_CORE_AUTO;
    if(rknn_set_core_mask(a->rknn_ctx,mask)<0) return fail();
    if(rknn_query(a->rknn_ctx,RKNN_QUERY_IN_OUT_NUM,&a->io_num,sizeof(a->io_num))<0) return fail();
    if(a->io_num.n_input!=1 || a->io_num.n_output<1 || a->io_num.n_output>8) return fail();
    a->input_attrs=(rknn_tensor_attr*)calloc(1,sizeof(rknn_tensor_attr));
    a->output_attrs=(rknn_tensor_attr*)calloc(a->io_num.n_output,sizeof(rknn_tensor_attr));
    if(!a->input_attrs || !a->output_attrs) return fail();
    if(rknn_query(a->rknn_ctx,RKNN_QUERY_INPUT_ATTR,a->input_attrs,sizeof(rknn_tensor_attr))<0) return fail();
    auto& in=a->input_attrs[0];
    if(in.n_dims!=4 || in.dims[0]!=1) return fail();
    if(in.fmt==RKNN_TENSOR_NCHW) {a->model_channel=in.dims[1];a->model_height=in.dims[2];a->model_width=in.dims[3];}
    else if(in.fmt==RKNN_TENSOR_NHWC) {a->model_height=in.dims[1];a->model_width=in.dims[2];a->model_channel=in.dims[3];}
    else return fail();
    if(a->model_channel!=3 || a->model_width<1 || a->model_height<1 || a->model_width>2048 || a->model_height>2048) return fail();
    for(unsigned i=0;i<a->io_num.n_output;++i) {
        auto& o=a->output_attrs[i];o.index=i;
        if(rknn_query(a->rknn_ctx,RKNN_QUERY_OUTPUT_ATTR,&o,sizeof(o))<0 || o.n_dims<2 || o.n_dims>RKNN_MAX_DIMS) return fail();
        const auto embed=o.dims[o.n_dims-1];
        if(embed==0 || embed>65536 || o.n_elems==0 || o.n_elems%embed) return fail();
        if(i==0) {a->model_embed_size=static_cast<int>(embed);a->model_image_token=static_cast<int>(o.n_elems/embed);}
        if(o.n_elems!=a->output_attrs[0].n_elems || embed!=static_cast<unsigned>(a->model_embed_size)) return fail();
    }
    if(static_cast<size_t>(a->model_image_token)*a->model_embed_size*a->io_num.n_output>32*1024*1024) return fail();
    return 0;
}
int release_imgenc(rknn_app_context_t* a) {
    free(a->input_attrs);free(a->output_attrs);
    if(a->rknn_ctx) rknn_destroy(a->rknn_ctx);
    *a={};return 0;
}
int run_imgenc(rknn_app_context_t* a,void* pixels,float* result) {
    rknn_input input{};input.index=0;input.type=RKNN_TENSOR_UINT8;input.fmt=RKNN_TENSOR_NHWC;
    input.size=static_cast<unsigned>(a->model_width*a->model_height*3);input.buf=pixels;
    if(rknn_inputs_set(a->rknn_ctx,1,&input)<0 || rknn_run(a->rknn_ctx,nullptr)<0) return -1;
    std::vector<rknn_output> outputs(a->io_num.n_output);
    for(unsigned i=0;i<outputs.size();++i){outputs[i].index=i;outputs[i].want_float=1;}
    if(rknn_outputs_get(a->rknn_ctx,a->io_num.n_output,outputs.data(),nullptr)<0) return -1;
    int status=0;size_t elements=static_cast<size_t>(a->model_image_token)*a->model_embed_size;
    for(const auto& o:outputs) if(!o.buf || o.size<elements*sizeof(float)) status=-1;
    if(!status) for(int t=0;t<a->model_image_token;++t) for(unsigned j=0;j<outputs.size();++j) {
        size_t destination=(static_cast<size_t>(t)*outputs.size()+j)*a->model_embed_size;
        memcpy(result+destination,static_cast<float*>(outputs[j].buf)+static_cast<size_t>(t)*a->model_embed_size,a->model_embed_size*sizeof(float));
    }
    if(rknn_outputs_release(a->rknn_ctx,a->io_num.n_output,outputs.data())<0) status=-1;
    return status;
}
