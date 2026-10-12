import argparse
import random
import pandas as pd
import openai
import tiktoken

import util
from agent import Agent
from secretary import Secretary
from stock import Stock
from log.custom_logger import log
from record import create_stock_record, create_trade_record, AgentRecordDaily, create_agentses_record

def get_agent(all_agents, order):
    for agent in all_agents:
        if agent.order == order:
            return agent
    return None

def handle_action(action, stock_deals, all_agents, stock, session):
    # action = {
    #     "agent": 1,
    #     "action_type": "buy" | "sell",
    #     "stock": "A" | "B",
    #     "amount": 10,
    #     "price": 10
    # }

    try:

        # ============================================================
        # BUY ACTION
        # ============================================================
        if action["action_type"] == "buy":

            for sell_action in stock_deals["sell"][:]:

                if action["price"] == sell_action["price"]:

                    # Amount that can actually be traded
                    close_amount = min(
                        action["amount"],
                        sell_action["amount"]
                    )

                    # Buyer buys the stock
                    get_agent(
                        all_agents,
                        action["agent"]
                    ).buy_stock(
                        stock.name,
                        action["price"],
                        close_amount
                    )

                    # Seller sells the stock
                    if sell_action["agent"] != -1:
                        get_agent(
                            all_agents,
                            sell_action["agent"]
                        ).sell_stock(
                            stock.name,
                            action["price"],
                            close_amount
                        )

                    # Record the transaction
                    stock.add_session_deal({
                        "price": action["price"],
                        "amount": close_amount
                    })

                    create_trade_record(
                        action["date"],
                        session,
                        stock.name,
                        action["agent"],
                        sell_action["agent"],
                        close_amount,
                        action["price"]
                    )

                    # ------------------------------------------------
                    # BUY ORDER STILL HAS REMAINING AMOUNT
                    # ------------------------------------------------
                    if action["amount"] > close_amount:

                        log.logger.info(
                            f"ACTION - BUY:{action['agent']}, "
                            f"SELL:{sell_action['agent']}, "
                            f"STOCK:{stock.name}, "
                            f"PRICE:{action['price']}, "
                            f"AMOUNT:{close_amount}"
                        )

                        # Remove completely filled sell order
                        stock_deals["sell"].remove(sell_action)

                        # Reduce remaining buy amount
                        action["amount"] -= close_amount

                    # ------------------------------------------------
                    # BUY ORDER COMPLETED
                    # ------------------------------------------------
                    else:

                        log.logger.info(
                            f"ACTION - BUY:{action['agent']}, "
                            f"SELL:{sell_action['agent']}, "
                            f"STOCK:{stock.name}, "
                            f"PRICE:{action['price']}, "
                            f"AMOUNT:{close_amount}"
                        )

                        # Reduce remaining sell order
                        sell_action["amount"] -= close_amount

                        return

            # --------------------------------------------------------
            # No matching sell order / remaining buy order
            # --------------------------------------------------------
            stock_deals["buy"].append(action)


        # ============================================================
        # SELL ACTION
        # ============================================================
        elif action["action_type"] == "sell":

            for buy_action in stock_deals["buy"][:]:

                if action["price"] == buy_action["price"]:

                    # Amount that can actually be traded
                    close_amount = min(
                        action["amount"],
                        buy_action["amount"]
                    )

                    # Seller sells the stock
                    get_agent(
                        all_agents,
                        action["agent"]
                    ).sell_stock(
                        stock.name,
                        action["price"],
                        close_amount
                    )

                    # Buyer buys the stock
                    get_agent(
                        all_agents,
                        buy_action["agent"]
                    ).buy_stock(
                        stock.name,
                        action["price"],
                        close_amount
                    )

                    # Record the transaction
                    stock.add_session_deal({
                        "price": action["price"],
                        "amount": close_amount
                    })

                    create_trade_record(
                        action["date"],
                        session,
                        stock.name,
                        buy_action["agent"],
                        action["agent"],
                        close_amount,
                        action["price"]
                    )

                    # ------------------------------------------------
                    # SELL ORDER STILL HAS REMAINING AMOUNT
                    # ------------------------------------------------
                    if action["amount"] > close_amount:

                        log.logger.info(
                            f"ACTION - BUY:{buy_action['agent']}, "
                            f"SELL:{action['agent']}, "
                            f"STOCK:{stock.name}, "
                            f"PRICE:{action['price']}, "
                            f"AMOUNT:{close_amount}"
                        )

                        # Remove completely filled buy order
                        stock_deals["buy"].remove(buy_action)

                        # Reduce remaining sell amount
                        action["amount"] -= close_amount

                    # ------------------------------------------------
                    # SELL ORDER COMPLETED
                    # ------------------------------------------------
                    else:

                        log.logger.info(
                            f"ACTION - BUY:{buy_action['agent']}, "
                            f"SELL:{action['agent']}, "
                            f"STOCK:{stock.name}, "
                            f"PRICE:{action['price']}, "
                            f"AMOUNT:{close_amount}"
                        )

                        # Reduce remaining buy order
                        buy_action["amount"] -= close_amount

                        return

            # --------------------------------------------------------
            # No matching buy order / remaining sell order
            # --------------------------------------------------------
            stock_deals["sell"].append(action)


        # ============================================================
        # INVALID ACTION
        # ============================================================
        else:

            log.logger.warning(
                f"Unknown action type received: "
                f"{action.get('action_type')}"
            )

            return

    except Exception as e:

        log.logger.error(
            f"handle_action error: {e}"
        )

        return


def simulation(args):
    # init
    secretary = Secretary(args.model)
    stock_a = Stock("A", util.STOCK_A_INITIAL_PRICE, 0, is_new=False)
    #stock_b = Stock("B", util.STOCK_B_INITIAL_PRICE, util.STOCK_B_PUBLISH, is_new=True)
    stock_b = Stock("B", util.STOCK_B_INITIAL_PRICE, 0, is_new=False)
    all_agents = []
    log.logger.debug("Agents initial...")
    for i in range(0, util.AGENTS_NUM):  # agents start from 0, -1 refers to admin
        agent = Agent(i, stock_a.get_price(), stock_b.get_price(), secretary, args.model)
        all_agents.append(agent)
        log.logger.debug("cash: {}, stock a: {}, stock b:{}, debt: {}".format(agent.cash, agent.stock_a_amount,
                                                                              agent.stock_b_amount, agent.loans))

    # start simulation
    last_day_forum_message = []
    stock_a_deals = {"sell": [], "buy": []}
    stock_b_deals = {"sell": [], "buy": []}
    # stock b publish
    # stock_b_deals["sell"].append({"agent": -1, "amount": util.STOCK_B_PUBLISH, "price": util.STOCK_B_INITIAL_PRICE})

    log.logger.debug("--------Simulation Start!--------")
    for date in range(1, util.TOTAL_DATE + 1):

        log.logger.debug(f"--------DAY {date}---------")
        # 除b发行外，删除前一天的所有交易
        stock_a_deals["sell"].clear()
        stock_a_deals["buy"].clear()
        stock_b_deals["buy"].clear()

        # tmp_action = next((action for action in stock_b_deals["sell"] if action["agent"] == -1), None)
        stock_b_deals["sell"].clear()
        # if tmp_action:
        #     tmp_action["price"] *= 0.9  # B发行折价
        #     if tmp_action["price"] < 1:
        #         log.logger.warning("WARNING: STOCK B WITHDRAW FROM MARKET!!!")
        #     stock_b_deals["sell"].append(tmp_action)

        # check if an agent needs to repay loans
        for agent in all_agents[:]:
            agent.chat_history.clear()  # 只保存当天的聊天记录
            agent.loan_repayment(date)

        # repayment days
        if date in util.REPAYMENT_DAYS:
            for agent in all_agents[:]:
                agent.interest_payment()

        # deal with cash<0 agents
        for agent in all_agents[:]:
            if agent.is_bankrupt:
                quit_sig = agent.bankrupt_process(stock_a.get_price(), stock_b.get_price())
                if quit_sig:
                    agent.quit = True
                    all_agents.remove(agent)

        # special events
        if date == util.EVENT_1_DAY:
            util.LOAN_RATE = util.EVENT_1_LOAN_RATE
            last_day_forum_message.append({"name": -1, "message": util.EVENT_1_MESSAGE})
        if date == util.EVENT_2_DAY:
            util.LOAN_RATE = util.EVENT_2_LOAN_RATE
            last_day_forum_message.append({"name": -1, "message": util.EVENT_2_MESSAGE})

        # agent decide whether to loan
        daily_agent_records = []
        for agent in all_agents:
            loan = agent.plan_loan(date, stock_a.get_price(), stock_b.get_price(), last_day_forum_message)
            daily_agent_records.append(AgentRecordDaily(date, agent.order, loan))

        for session in range(1, util.TOTAL_SESSION + 1):
            log.logger.debug(f"SESSION {session}")
            # 随机定义交易顺序
            sequence = list(range(len(all_agents)))
            random.shuffle(sequence)
            for i in sequence:
                agent = all_agents[i]
                # if agent.is_bankrupt:  # cash<0的当天停止交易，交易时段结束后贩卖股票
                #     continue

                action = agent.plan_stock(date, session, stock_a, stock_b, stock_a_deals, stock_b_deals)
                proper, cash, valua_a, value_b = agent.get_proper_cash_value(stock_a.get_price(), stock_b.get_price())
                create_agentses_record(agent.order, date, session, proper, cash, valua_a, value_b, action)
                action["agent"] = agent.order
                action["date"] = date
                if not action["action_type"] == "no":
                    if action["stock"] == 'A':
                        handle_action(action, stock_a_deals, all_agents, stock_a, session)
                    else:
                        handle_action(action, stock_b_deals, all_agents, stock_b, session)

            # 交易时段结束，更新股票价格
            stock_a.update_price(date)
            stock_b.update_price(date)
            create_stock_record(date, session, stock_a.get_price(), stock_b.get_price())


        # agent预测明天行动
        for idx, agent in enumerate(all_agents):
            estimation = agent.next_day_estimate()
            log.logger.info("Agent {} tomorrow estimation: {}".format(agent.order, estimation))
            if idx >= len(daily_agent_records):
                break
            daily_agent_records[idx].add_estimate(estimation)
            daily_agent_records[idx].write_to_excel()
        daily_agent_records.clear()

        # 交易日结束，论坛信息更新
        last_day_forum_message.clear()
        log.logger.debug(f"DAY {date} ends, display forum messages...")
        for agent in all_agents:
            chat_history = agent.chat_history
            message = agent.post_message()
            log.logger.info("Agent {} says: {}".format(agent.order, message))
            last_day_forum_message.append({"name": agent.order, "message": message})



    log.logger.debug("--------Simulation finished!--------")
    log.logger.debug("--------Agents action history--------")
    # for agent in all_agents:
    #     log.logger.debug(f"Agent {agent.order} action history:")
    #     log.logger.info(agent.action_history)
    # log.logger.debug("--------Stock deal history--------")
    # for stock in [stock_a, stock_b]:
    #     log.logger.debug(f"Stock {stock.name} deal history:")
    #     log.logger.info(stock.history)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="gemini-3.1-flash-lite", help="model name")
    args = parser.parse_args()
    simulation(args)
