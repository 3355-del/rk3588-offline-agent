// One-shot or session-owned resident RK3588 inference, using the pinned SDK ABI.
#include <stddef.h> // SDK declarations use global size_t.
#include "rkllm.h"
#include "image_enc.h"
#include "npu_session_lease.h"
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
#include <mutex>
#include <cstring>
#include <filesystem>
#include <csignal>
#include <sys/prctl.h>
#include <unistd.h>
#include <chrono>
struct Result {std::string text;bool failed=false;std::mutex lock;
    std::chrono::steady_clock::time_point started;
    double firstTextMs=-1;
};
int callback(RKLLMResult* r,void* userdata,LLMCallState state) {
    auto* result=static_cast<Result*>(userdata);if(!result) return 0;
    std::lock_guard<std::mutex> guard(result->lock);
    if(state==RKLLM_RUN_ERROR) result->failed=true;
    if(state==RKLLM_RUN_NORMAL && r && r->text) {
        size_t n=std::strlen(r->text);
        if(n && result->firstTextMs<0)result->firstTextMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-result->started).count();
        if(result->text.size()+n>1024*1024) result->failed=true;
        else result->text.append(r->text,n);
    }
    return 0;
}
struct Runtime {
    NpuSessionLease lease; // Destroyed only after native contexts have been released.
    LLMHandle llm=nullptr;rknn_app_context_t vision{};
    ~Runtime(){if(llm)rkllm_destroy(llm);release_imgenc(&vision);}
};
std::string read(const char* path,size_t limit) {
    std::ifstream in(path,std::ios::binary);if(!in)throw std::runtime_error("input file cannot be opened");
    std::string value;char buf[4096];
    while(in){in.read(buf,sizeof(buf));value.append(buf,static_cast<size_t>(in.gcount()));if(value.size()>limit)throw std::runtime_error("input file too large");}
    return value;
}
int infer(int argc,char** argv,Runtime& runtime,Result& result) {
    // model.rkllm vision.rknn|- prompt.txt rgb.bin|- width height answer.txt max_tokens context
    if(argc!=10){std::cerr<<"usage: edge-rkllm model vision prompt rgb width height answer max_tokens context\n";return 2;}
    try {
        result.text.clear();result.failed=false;
        result.started=std::chrono::steady_clock::now();result.firstTextMs=-1;
        int width=std::stoi(argv[5]),height=std::stoi(argv[6]),tokens=std::stoi(argv[8]),context=std::stoi(argv[9]);
        if(width<1||width>2048||height<1||height>2048)throw std::runtime_error("invalid image dimensions");
        if(tokens<1||tokens>2048||context<512||context>8192||tokens>=context)throw std::runtime_error("invalid token budget");
        std::string prompt=read(argv[3],65536);if(prompt.empty())throw std::runtime_error("empty prompt");
        runtime.lease.acquire(true);
        RKLLMParam param=rkllm_createDefaultParam();param.model_path=argv[1];param.max_new_tokens=tokens;param.max_context_len=context;param.top_k=1;param.skip_special_token=true;param.extend_param.base_domain_id=1;
        RKLLMCallback hooks{};hooks.result_callback=callback;
        if(!runtime.llm && rkllm_init(&runtime.llm,&param,&hooks)!=0)throw std::runtime_error("rkllm_init failed; check runtime/model/driver versions");
        if(rkllm_clear_kv_cache(runtime.llm,0,nullptr,nullptr)!=0)throw std::runtime_error("cannot reset model KV cache");
        RKLLMInput input{};RKLLMInferParam infer{};infer.mode=RKLLM_INFER_GENERATE;infer.keep_history=0;input.role="user";
        std::vector<float> embeddings;std::string pixels;
        if(std::string(argv[4])!="-") {
            if(!runtime.vision.rknn_ctx && init_imgenc(argv[2],&runtime.vision,3)!=0)throw std::runtime_error("vision model init/shape check failed");
            auto& v=runtime.vision;
            if(width!=v.model_width||height!=v.model_height)throw std::runtime_error("configured vision dimensions do not match RKNN model");
            pixels=read(argv[4],static_cast<size_t>(width)*height*3);
            if(pixels.size()!=static_cast<size_t>(width)*height*3)throw std::runtime_error("invalid RGB input size");
            if(v.model_image_token+tokens+256>=context)throw std::runtime_error("context too small for image tokens and response");
            embeddings.resize(static_cast<size_t>(v.model_image_token)*v.model_embed_size*v.io_num.n_output);
            if(run_imgenc(&v,pixels.data(),embeddings.data())!=0)throw std::runtime_error("vision encoding failed");
            prompt="<image>"+prompt;input.input_type=RKLLM_INPUT_MULTIMODAL;input.multimodal_input.prompt=prompt.data();
            input.multimodal_input.image.image_embed=embeddings.data();input.multimodal_input.image.n_image_tokens=v.model_image_token;input.multimodal_input.image.n_image=1;
            input.multimodal_input.image.image_start="<|vision_start|>";input.multimodal_input.image.image_end="<|vision_end|>";input.multimodal_input.image.image_content="<|image_pad|>";
            input.multimodal_input.image.image_width=width;input.multimodal_input.image.image_height=height;
        } else {input.input_type=RKLLM_INPUT_PROMPT;input.prompt_input=prompt.data();}
        if(rkllm_run(runtime.llm,&input,&infer,&result)!=0 || result.failed)throw std::runtime_error("RKLLM generation failed");
        std::ofstream out(argv[7],std::ios::binary|std::ios::trunc);out<<result.text;out.close();if(!out)throw std::runtime_error("cannot write answer");
        std::ofstream metrics(std::string(argv[7])+".metrics.json");
        metrics<<"{\"native_first_text_ms\":"<<result.firstTextMs<<",\"native_total_ms\":"
            <<std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-result.started).count()<<"}";
        metrics.close();if(!metrics)throw std::runtime_error("cannot write metrics");
        return 0;
    } catch(const std::exception& e){std::cerr<<"EDGE_ERROR: "<<e.what()<<'\n';return 1;}
}

int main(int argc,char** argv) {
    Result result;Runtime runtime; // callback state outlives runtime destruction
    if(argc<2 || std::string(argv[1])!="--serve") return infer(argc,argv,runtime,result);
    // --serve model vision width height max_tokens context private_directory
    if(argc!=9) return 2;
    const auto parent=getppid();
    if(parent==1 || prctl(PR_SET_PDEATHSIG,SIGTERM)!=0 || getppid()!=parent) return 2;
    try {
        const std::filesystem::path root=argv[8];
        if(!std::filesystem::is_directory(root)) return 2;
        {std::ofstream ready(root/"ready");ready<<"edge-resident-v1";if(!ready) return 2;}
        std::string id;
        while(std::getline(std::cin,id)) {
            if(id.size()!=32 || id.find_first_not_of("0123456789abcdef")!=std::string::npos) return 2;
            const auto job=root/id;
            std::vector<std::string> args={argv[0],argv[2],argv[3],(job/"prompt.txt").string(),
                std::filesystem::exists(job/"rgb.bin")?(job/"rgb.bin").string():"-",
                argv[4],argv[5],(job/"answer.txt").string(),argv[6],argv[7]};
            std::vector<char*> ptrs;for(auto& arg:args) ptrs.push_back(arg.data());
            const int status=infer(static_cast<int>(ptrs.size()),ptrs.data(),runtime,result);
            {std::ofstream done(job/"done.tmp");done<<status;done.close();if(!done) return 2;}
            std::filesystem::rename(job/"done.tmp",job/"done");
            if(status) return status; // Do not reuse a context after an SDK error.
        }
        return 0;
    } catch(const std::exception& e){std::cerr<<"EDGE_ERROR: "<<e.what()<<'\n';return 1;}
}
