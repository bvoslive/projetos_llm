#Importando bibliotecas
import os
from dotenv import load_dotenv
from typing import TypedDict, List, Literal
from langgraph.graph import END, StateGraph
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

# Carrega variáveis do .env
load_dotenv('.env')
openai_key = os.getenv("OPENAI_API_KEY")

# Abrir e ler o conteúdo
with open('news.txt', 'r', encoding='utf-8') as file:
    news_text = file.read()

# Exibir o conteúdo
print(news_text)

#Tipo de investidor
investor_type = "longo_prazo"  # Pode ser "longo_prazo", "curto_prazo" ou "fora_papel"

# Configuração do modelo (substitua pela sua API key)
llm = ChatOpenAI(model="gpt-4-turbo", temperature=0, api_key=openai_key)

# Definindo tipos
class State(TypedDict):
    news_text: str
    investor_type: Literal["longo_prazo", "curto_prazo", "fora_papel"]
    sentiment: Literal["otimista", "neutro", "pessimista"] | None
    entities: List[dict] | None
    stock_price: float | None
    news_type: Literal["pontual", "estrutural", "regulatório", "financeira"] | None
    price_change: str | None
    recommendations: List[str] | None

# Funções para cada nó do grafo
def analyze_sentiment(state: State):
    print("\nAnalisando sentimento da notícia...")
    response = llm.invoke([
        HumanMessage(content=f"""Analise o sentimento desta notícia financeira:
        {state['news_text']}
        
        Retorne apenas uma das três opções: otimista, neutro ou pessimista""")
    ])
    return {"sentiment": response.content.lower()}

def extract_entities(state: State):
    print("\nExtraindo entidades financeiras...")
    response = llm.invoke([
        HumanMessage(content=f"""Identifique todas as entidades financeiras relevantes nesta notícia:
        {state['news_text']}
        
        Para cada entidade, retorne como JSON com campos: nome, tipo (empresa, índice, setor), ticker (se disponível)""")
    ])
    # Parse simples - em produção usar um parser robusto
    try:
        entities = eval(response.content)
    except:
        entities = []
    return {"entities": entities}

def get_stock_price(state: State):
    print("\nObtendo preço da ação...")
    # Simulação - em produção integrar com API de mercado
    main_entity = next((e for e in state["entities"] if e["tipo"] == "empresa"), None)
    if main_entity:
        ticker = main_entity.get("ticker", "PETR4")  # Default para exemplo
        price = 212.50  # Simulado
        print(f"Preço simulado para {ticker}: R${price}")
        return {"stock_price": price}
    return {"stock_price": None}

def classify_news_type(state: State):
    print("\nClassificando tipo de notícia...")
    response = llm.invoke([
        HumanMessage(content=f"""Classifique o tipo desta notícia financeira:
        {state['news_text']}
        
        Opções: pontual (evento único), estrutural (mudança no modelo de negócios), 
        regulatório (mudanças em leis/regulações), financeira (resultados/lucros/dívidas)""")
    ])
    return {"news_type": response.content.lower()}

def check_price_movement(state: State):
    print("\nVerificando movimento do preço...")
    # Simulação - em produção verificar histórico
    movement = "subiu muito" if state["sentiment"] == "otimista" else "caiu muito"
    return {"price_change": movement}

def generate_recommendations(state: State):
    print("\nGerando recomendações...")
    
    investor_map = {
        "longo_prazo": "investidor de longo prazo",
        "curto_prazo": "trader de curto prazo",
        "fora_papel": "investidor fora do papel"
    }
    
    prompt = f"""Com base nesta análise:
    - Sentimento: {state['sentiment']}
    - Tipo de notícia: {state['news_type']}
    - Movimento do preço: {state['price_change']}
    - Entidades envolvidas: {state['entities']}
    
    Gere recomendações para um {investor_map[state['investor_type']]}.
    Seja específico e considere o perfil de investimento."""
    
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"recommendations": [r.strip() for r in response.content.split("\n") if r.strip()]}

def neutral_analysis(state: State):
    print("\nAnalisando notícia neutra...")
    response = llm.invoke([
        HumanMessage(content=f"""Esta notícia foi classificada como neutra, 
        mas avalie se é ligeiramente positiva ou negativa:
        {state['news_text']}
        
        Retorne 'ligeiramente positiva' ou 'ligeiramente negativa'""")
    ])
    return {"sentiment": f"neutro ({response.content.lower()})"}

# Definindo o fluxo do grafo
workflow = StateGraph(State)

# Adicionando nós
workflow.add_node("analyze_sentiment", analyze_sentiment)
workflow.add_node("extract_entities", extract_entities)
workflow.add_node("get_stock_price", get_stock_price)
workflow.add_node("classify_news_type", classify_news_type)
workflow.add_node("check_price_movement", check_price_movement)
workflow.add_node("generate_recommendations", generate_recommendations)
workflow.add_node("neutral_analysis", neutral_analysis)

# Definindo fluxo inicial
workflow.set_entry_point("analyze_sentiment")
workflow.add_edge("analyze_sentiment", "extract_entities")

# Condições após extração de entidades
def route_after_entities(state: State):
    if state["sentiment"] == "neutro":
        return "neutral_analysis"
    else:
        return "get_stock_price"

workflow.add_conditional_edges(
    "extract_entities",
    route_after_entities,
    {
        "neutral_analysis": "neutral_analysis",
        "get_stock_price": "get_stock_price",
    },
)

# Fluxo para notícias otimistas/pessimistas
workflow.add_edge("get_stock_price", "classify_news_type")
workflow.add_edge("classify_news_type", "check_price_movement")
workflow.add_edge("check_price_movement", "generate_recommendations")
workflow.add_edge("generate_recommendations", END)

# Fluxo para notícias neutras
workflow.add_edge("neutral_analysis", END)

# Compilando o grafo
app = workflow.compile()

# Executando o grafo
result = app.invoke({
    "news_text": news_text,
    "investor_type": investor_type
})

## Exibindo resultados
print("\n\n=== RESULTADOS DA ANÁLISE ===")
print(f"Sentimento: {result['sentiment']}")
print("\nEntidades identificadas:")
for entity in result['entities']:
    print(f"- {entity['nome']} ({entity['tipo']}, Ticker: {entity.get('ticker', 'N/A')})")

if result['sentiment'] != "neutro":
    print(f"\nTipo de notícia: {result['news_type']}")
    print(f"Movimento do preço: {result['price_change']}")
    print("\nRecomendações:")
    for rec in result['recommendations']:
        print(f"- {rec}")
else:
    print(f"\nAnálise neutra: {result['sentiment']}")

