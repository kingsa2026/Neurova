#!/bin/bash
# Neurova Helm Chart 部署脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Helm 是否安装
check_helm() {
    if ! command -v helm &> /dev/null; then
        print_error "Helm 未安装"
        print_info "请先安装 Helm: https://helm.sh/docs/intro/install/"
        exit 1
    fi
    print_success "Helm 已安装: $(helm version --short)"
}

# 检查 Kubernetes 连接
check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl 未安装"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        print_error "无法连接到 Kubernetes 集群"
        exit 1
    fi
    print_success "Kubernetes 集群连接正常"
}

# 检查 Helm Chart
lint_chart() {
    print_info "检查 Helm Chart 语法..."
    if helm lint neurova; then
        print_success "Helm Chart 语法检查通过"
    else
        print_error "Helm Chart 语法检查失败"
        exit 1
    fi
}

# 部署函数
deploy() {
    local environment=$1
    local namespace=$2
    local release_name=$3
    
    print_info "部署到 $environment 环境..."
    
    # 创建命名空间
    if ! kubectl get namespace "$namespace" &> /dev/null; then
        print_info "创建命名空间: $namespace"
        kubectl create namespace "$namespace"
    fi
    
    # 构建 Helm 命令
    local helm_cmd="helm upgrade --install $release_name neurova --namespace $namespace"
    
    # 根据环境选择配置文件
    case $environment in
        "production"|"prod")
            helm_cmd="$helm_cmd -f neurova/values-production.yaml"
            ;;
        "development"|"dev")
            helm_cmd="$helm_cmd -f neurova/values-development.yaml"
            ;;
        *)
            print_warning "未知环境: $environment，使用默认配置"
            ;;
    esac
    
    # 执行部署
    print_info "执行部署命令..."
    eval $helm_cmd
    
    if [ $? -eq 0 ]; then
        print_success "部署成功！"
        print_info "查看部署状态:"
        echo "  kubectl get pods -n $namespace -l app.kubernetes.io/name=neurova"
        echo "  helm status $release_name -n $namespace"
    else
        print_error "部署失败"
        exit 1
    fi
}

# 显示使用说明
show_usage() {
    echo "Neurova Helm Chart 部署脚本"
    echo ""
    echo "使用方法:"
    echo "  $0 [命令] [选项]"
    echo ""
    echo "命令:"
    echo "  deploy      部署应用"
    echo "  lint        检查 Helm Chart 语法"
    echo "  status      查看部署状态"
    echo "  uninstall   卸载应用"
    echo "  template    渲染模板（不部署）"
    echo ""
    echo "选项:"
    echo "  -e, --environment  环境 (production/development) [默认: development]"
    echo "  -n, --namespace    命名空间 [默认: neurova]"
    echo "  -r, --release      Release 名称 [默认: neurova]"
    echo "  -h, --help         显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 deploy -e production -n neurova-prod"
    echo "  $0 lint"
    echo "  $0 status -n neurova"
    echo "  $0 uninstall -n neurova"
}

# 主函数
main() {
    local command=""
    local environment="development"
    local namespace="neurova"
    local release_name="neurova"
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -e|--environment)
                environment="$2"
                shift 2
                ;;
            -n|--namespace)
                namespace="$2"
                shift 2
                ;;
            -r|--release)
                release_name="$2"
                shift 2
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            deploy|lint|status|uninstall|template)
                command="$1"
                shift
                ;;
            *)
                print_error "未知参数: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # 检查命令
    if [ -z "$command" ]; then
        show_usage
        exit 1
    fi
    
    # 检查依赖
    check_helm
    check_kubectl
    
    # 执行命令
    case $command in
        "deploy")
            lint_chart
            deploy "$environment" "$namespace" "$release_name"
            ;;
        "lint")
            lint_chart
            ;;
        "status")
            print_info "查看部署状态..."
            helm status "$release_name" -n "$namespace" || true
            kubectl get pods -n "$namespace" -l app.kubernetes.io/name=neurova
            ;;
        "uninstall")
            print_info "卸载应用..."
            helm uninstall "$release_name" -n "$namespace" || true
            print_success "应用已卸载"
            ;;
        "template")
            print_info "渲染模板..."
            helm template "$release_name" neurova -n "$namespace"
            ;;
    esac
}

# 运行主函数
main "$@"