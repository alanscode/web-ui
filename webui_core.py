import pdb
import logging
import asyncio
import os
import glob
import json
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from browser_use.agent.service import Agent
from playwright.async_api import async_playwright
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import (
    BrowserContextConfig,
    BrowserContextWindowSize,
)
from langchain_ollama import ChatOllama

from src.utils.agent_state import AgentState
from src.utils import utils
from src.agent.custom_agent import CustomAgent
from src.browser.custom_browser import CustomBrowser
from src.agent.custom_prompts import CustomSystemPrompt, CustomAgentMessagePrompt
from src.browser.custom_context import BrowserContextConfig, CustomBrowserContext
from src.controller.custom_controller import CustomController
from src.utils.default_config_settings import default_config, load_config_from_file, save_config_to_file, save_current_config, update_ui_from_config
from src.utils.utils import update_model_dropdown, get_latest_files, capture_screenshot

# Global variables for persistence
_global_browser = None
_global_browser_context = None
_global_agent = None

# Create the global agent state instance
_global_agent_state = AgentState()

def resolve_sensitive_env_variables(text):
    """
    Replace environment variable placeholders ($SENSITIVE_*) with their values.
    Only replaces variables that start with SENSITIVE_.
    """
    if not text:
        return text
        
    import re
    
    # Find all $SENSITIVE_* patterns
    env_vars = re.findall(r'\$SENSITIVE_[A-Za-z0-9_]*', text)
    
    result = text
    for var in env_vars:
        # Remove the $ prefix to get the actual environment variable name
        env_name = var[1:]  # removes the $
        env_value = os.getenv(env_name)
        if env_value is not None:
            # Replace $SENSITIVE_VAR_NAME with its value
            result = result.replace(var, env_value)
        
    return result

async def stop_agent():
    """Request the agent to stop and update UI with enhanced feedback"""
    global _global_agent_state, _global_browser_context, _global_browser, _global_agent

    try:
        # Request stop
        _global_agent.stop()

        # Update UI immediately
        message = "Stop requested - the agent will halt at the next safe point"
        logger.info(f"🛑 {message}")

        # Return UI updates
        return (
            message,                                        # errors_output
            "Stopping...",  # stop_button value
            False,  # stop_button interactive
            False,  # run_button interactive
        )
    except Exception as e:
        error_msg = f"Error during stop: {str(e)}"
        logger.error(error_msg)
        return (
            error_msg,
            "Stop",
            True,
            True
        )
        
async def stop_research_agent():
    """Request the agent to stop and update UI with enhanced feedback"""
    global _global_agent_state, _global_browser_context, _global_browser

    try:
        # Request stop
        _global_agent_state.request_stop()

        # Update UI immediately
        message = "Stop requested - the agent will halt at the next safe point"
        logger.info(f"🛑 {message}")

        # Return UI updates
        return (                                   
            "Stopping...",  # stop_button value
            False,  # stop_button interactive
            False,  # run_button interactive
        )
    except Exception as e:
        error_msg = f"Error during stop: {str(e)}"
        logger.error(error_msg)
        return (
            "Stop",
            True,
            True
        )

async def run_browser_agent(
        agent_type,
        llm_provider,
        llm_model_name,
        llm_num_ctx,
        llm_temperature,
        llm_base_url,
        llm_api_key,
        use_own_browser,
        keep_browser_open,
        headless,
        disable_security,
        window_w,
        window_h,
        save_recording_path,
        save_agent_history_path,
        save_trace_path,
        enable_recording,
        task,
        add_infos,
        max_steps,
        use_vision,
        max_actions_per_step,
        tool_calling_method,
        chrome_cdp
):
    global _global_agent_state
    _global_agent_state.clear_stop()  # Clear any previous stop requests

    try:
        # Disable recording if the checkbox is unchecked
        if not enable_recording:
            save_recording_path = None

        # Ensure the recording directory exists if recording is enabled
        if save_recording_path:
            os.makedirs(save_recording_path, exist_ok=True)

        # Get the list of existing videos before the agent runs
        existing_videos = set()
        if save_recording_path:
            existing_videos = set(
                glob.glob(os.path.join(save_recording_path, "*.[mM][pP]4"))
                + glob.glob(os.path.join(save_recording_path, "*.[wW][eE][bB][mM]"))
            )

        task = resolve_sensitive_env_variables(task)

        # Run the agent
        llm = utils.get_llm_model(
            provider=llm_provider,
            model_name=llm_model_name,
            num_ctx=llm_num_ctx,
            temperature=llm_temperature,
            base_url=llm_base_url,
            api_key=llm_api_key,
        )
        if agent_type == "org":
            final_result, errors, model_actions, model_thoughts, trace_file, history_file = await run_org_agent(
                llm=llm,
                use_own_browser=use_own_browser,
                keep_browser_open=keep_browser_open,
                headless=headless,
                disable_security=disable_security,
                window_w=window_w,
                window_h=window_h,
                save_recording_path=save_recording_path,
                save_agent_history_path=save_agent_history_path,
                save_trace_path=save_trace_path,
                task=task,
                add_infos=add_infos,
                max_steps=max_steps,
                use_vision=use_vision,
                max_actions_per_step=max_actions_per_step,
                tool_calling_method=tool_calling_method,
                chrome_cdp=chrome_cdp
            )
        elif agent_type == "custom":
            final_result, errors, model_actions, model_thoughts, trace_file, history_file = await run_custom_agent(
                llm=llm,
                use_own_browser=use_own_browser,
                keep_browser_open=keep_browser_open,
                headless=headless,
                disable_security=disable_security,
                window_w=window_w,
                window_h=window_h,
                save_recording_path=save_recording_path,
                save_agent_history_path=save_agent_history_path,
                save_trace_path=save_trace_path,
                task=task,
                add_infos=add_infos,
                max_steps=max_steps,
                use_vision=use_vision,
                max_actions_per_step=max_actions_per_step,
                tool_calling_method=tool_calling_method,
                chrome_cdp=chrome_cdp
            )
        else:
            raise ValueError(f"Invalid agent type: {agent_type}")

        # Get the list of videos after the agent runs (if recording is enabled)
        latest_video = None
        if save_recording_path:
            new_videos = set(
                glob.glob(os.path.join(save_recording_path, "*.[mM][pP]4"))
                + glob.glob(os.path.join(save_recording_path, "*.[wW][eE][bB][mM]"))
            )
            if new_videos - existing_videos:
                latest_video = list(new_videos - existing_videos)[0]  # Get the first new video
                
                # Extract just the filename from the path for the video ID
                # Remove the file extension to avoid duplication in the client
                latest_video_id = os.path.basename(latest_video)
                latest_video_id = os.path.splitext(latest_video_id)[0]  # Remove extension
                
                # Update the history file with the video ID if it exists
                if history_file and os.path.exists(history_file):
                    try:
                        with open(history_file, 'r') as f:
                            history_data = json.load(f)
                        
                        # Add the video ID to the history data
                        history_data['video_id'] = latest_video_id
                        history_data['original_prompt'] = task
                        
                        # Enhance history data with detailed element information for Cypress testing
                        if 'history' in history_data:
                            for step in history_data['history']:
                                if 'model_output' in step and 'action' in step['model_output']:
                                    action_list = step['model_output']['action']
                                    for action_item in action_list:
                                        # Enhance click actions with more element details
                                        if 'click' in action_item:
                                            # Add element type and purpose if available from observation
                                            if 'observation' in step:
                                                action_item['click']['element_type'] = _extract_element_type(step['observation'])
                                                action_item['click']['element_purpose'] = _extract_element_purpose(step['observation'])
                                        
                                        # Enhance type actions with field information
                                        elif 'type' in action_item:
                                            if 'observation' in step:
                                                action_item['type']['field_type'] = _extract_field_type(step['observation'])
                                                action_item['type']['field_purpose'] = _extract_field_purpose(step['observation'])
                        
                        # Write the updated history data back to the file
                        with open(history_file, 'w') as f:
                            json.dump(history_data, f, indent=2)
                    except Exception as e:
                        logger.error(f"Error updating history file with enhanced data: {str(e)}")

        return (
            final_result,
            errors,
            model_actions,
            model_thoughts,
            latest_video,
            trace_file,
            history_file,
            "Stop",  # Re-enable stop button
            True,  # stop_button interactive
            True    # Re-enable run button
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        errors = str(e) + "\n" + traceback.format_exc()
        return (
            '',                                         # final_result
            errors,                                     # errors
            '',                                         # model_actions
            '',                                         # model_thoughts
            None,                                       # latest_video
            None,                                       # history_file
            None,                                       # trace_file
            "Stop",  # Re-enable stop button
            True,  # stop_button interactive
            True    # Re-enable run button
        )


async def run_org_agent(
        llm,
        use_own_browser,
        keep_browser_open,
        headless,
        disable_security,
        window_w,
        window_h,
        save_recording_path,
        save_agent_history_path,
        save_trace_path,
        task,
        add_infos,
        max_steps,
        use_vision,
        max_actions_per_step,
        tool_calling_method,
        chrome_cdp
):
    try:
        global _global_browser, _global_browser_context, _global_agent_state, _global_agent
        
        # Clear any previous stop request
        _global_agent_state.clear_stop()

        extra_chromium_args = [f"--window-size={window_w},{window_h}"]
        cdp_url = chrome_cdp

        if use_own_browser:
            cdp_url = os.getenv("CHROME_CDP", chrome_cdp)
            chrome_path = os.getenv("CHROME_PATH", None)
            if chrome_path == "":
                chrome_path = None
            chrome_user_data = os.getenv("CHROME_USER_DATA", None)
            if chrome_user_data:
                extra_chromium_args += [f"--user-data-dir={chrome_user_data}"]
        else:
            chrome_path = None
            
        if _global_browser is None:

            _global_browser = Browser(
                config=BrowserConfig(
                    headless=headless,
                    cdp_url=cdp_url,
                    disable_security=disable_security,
                    chrome_instance_path=chrome_path,
                    extra_chromium_args=extra_chromium_args,
                )
            )

        if _global_browser_context is None:
            _global_browser_context = await _global_browser.new_context(
                config=BrowserContextConfig(
                    trace_path=save_trace_path if save_trace_path else None,
                    save_recording_path=save_recording_path if save_recording_path else None,
                    cdp_url=cdp_url,
                    no_viewport=False,
                    browser_window_size=BrowserContextWindowSize(
                        width=window_w, height=window_h
                    ),
                )
            )

        if _global_agent is None:
            _global_agent = Agent(
                task=task,
                llm=llm,
                use_vision=use_vision,
                browser=_global_browser,
                browser_context=_global_browser_context,
                max_actions_per_step=max_actions_per_step,
                tool_calling_method=tool_calling_method
            )
        history = await _global_agent.run(max_steps=max_steps)

        history_file = os.path.join(save_agent_history_path, f"{_global_agent.agent_id}.json")
        _global_agent.save_history(history_file)
        
        # Add original prompt and additional info to the history file
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history_data = json.load(f)
                
                # Add the original prompt and additional info to the history data
                history_data['original_prompt'] = task
                if add_infos:
                    history_data['add_infos'] = add_infos
                
                # Enhance history data with detailed element information for Cypress testing
                if 'history' in history_data:
                    for step in history_data['history']:
                        if 'model_output' in step and 'action' in step['model_output']:
                            action_list = step['model_output']['action']
                            for action_item in action_list:
                                # Enhance click actions with more element details
                                if 'click' in action_item:
                                    # Add element type and purpose if available from observation
                                    if 'observation' in step:
                                        action_item['click']['element_type'] = _extract_element_type(step['observation'])
                                        action_item['click']['element_purpose'] = _extract_element_purpose(step['observation'])
                                
                                # Enhance type actions with field information
                                elif 'type' in action_item:
                                    if 'observation' in step:
                                        action_item['type']['field_type'] = _extract_field_type(step['observation'])
                                        action_item['type']['field_purpose'] = _extract_field_purpose(step['observation'])
                
                # Write the updated history data back to the file
                with open(history_file, 'w') as f:
                    json.dump(history_data, f, indent=2)
                    
                # Generate Cypress test for this history file
                from src.utils.cypress_generator import generate_cypress_test
                cypress_test_path = generate_cypress_test(history_file)
                logger.info(f"Generated Cypress test: {cypress_test_path}")
            except Exception as e:
                logger.error(f"Error updating history file with enhanced data: {str(e)}")

        final_result = history.final_result()
        errors = history.errors()
        model_actions = history.model_actions()
        model_thoughts = history.model_thoughts()

        trace_file = get_latest_files(save_trace_path)

        return final_result, errors, model_actions, model_thoughts, trace_file.get('.zip'), history_file
    except Exception as e:
        import traceback
        traceback.print_exc()
        errors = str(e) + "\n" + traceback.format_exc()
        return '', errors, '', '', None, None
    finally:
        _global_agent = None
        # Handle cleanup based on persistence configuration
        if not keep_browser_open:
            if _global_browser_context:
                await _global_browser_context.close()
                _global_browser_context = None

            if _global_browser:
                await _global_browser.close()
                _global_browser = None

async def run_custom_agent(
        llm,
        use_own_browser,
        keep_browser_open,
        headless,
        disable_security,
        window_w,
        window_h,
        save_recording_path,
        save_agent_history_path,
        save_trace_path,
        task,
        add_infos,
        max_steps,
        use_vision,
        max_actions_per_step,
        tool_calling_method,
        chrome_cdp
):
    try:
        global _global_browser, _global_browser_context, _global_agent_state, _global_agent

        # Clear any previous stop request
        _global_agent_state.clear_stop()

        extra_chromium_args = [f"--window-size={window_w},{window_h}"]
        cdp_url = chrome_cdp
        if use_own_browser:
            cdp_url = os.getenv("CHROME_CDP", chrome_cdp)

            chrome_path = os.getenv("CHROME_PATH", None)
            if chrome_path == "":
                chrome_path = None
            chrome_user_data = os.getenv("CHROME_USER_DATA", None)
            if chrome_user_data:
                extra_chromium_args += [f"--user-data-dir={chrome_user_data}"]
        else:
            chrome_path = None

        controller = CustomController()

        # Initialize global browser if needed
        #if chrome_cdp not empty string nor None
        if ((_global_browser is None) or (cdp_url and cdp_url != "" and cdp_url != None)) :
            _global_browser = CustomBrowser(
                config=BrowserConfig(
                    headless=headless,
                    disable_security=disable_security,
                    cdp_url=cdp_url,
                    chrome_instance_path=chrome_path,
                    extra_chromium_args=extra_chromium_args,
                )
            )

        if (_global_browser_context is None  or (chrome_cdp and cdp_url != "" and cdp_url != None)):
            _global_browser_context = await _global_browser.new_context(
                config=BrowserContextConfig(
                    trace_path=save_trace_path if save_trace_path else None,
                    save_recording_path=save_recording_path if save_recording_path else None,
                    no_viewport=False,
                    browser_window_size=BrowserContextWindowSize(
                        width=window_w, height=window_h
                    ),
                )
            )


        # Create and run agent
        if _global_agent is None:
            _global_agent = CustomAgent(
                task=task,
                add_infos=add_infos,
                use_vision=use_vision,
                llm=llm,
                browser=_global_browser,
                browser_context=_global_browser_context,
                controller=controller,
                system_prompt_class=CustomSystemPrompt,
                agent_prompt_class=CustomAgentMessagePrompt,
                max_actions_per_step=max_actions_per_step,
                tool_calling_method=tool_calling_method
            )
        history = await _global_agent.run(max_steps=max_steps)

        history_file = os.path.join(save_agent_history_path, f"{_global_agent.agent_id}.json")
        _global_agent.save_history(history_file)
        
        # Add original prompt and additional info to the history file
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history_data = json.load(f)
                
                # Add the original prompt and additional info to the history data
                history_data['original_prompt'] = task
                if add_infos:
                    history_data['add_infos'] = add_infos
                
                # Enhance history data with detailed element information for Cypress testing
                if 'history' in history_data:
                    for step in history_data['history']:
                        if 'model_output' in step and 'action' in step['model_output']:
                            action_list = step['model_output']['action']
                            for action_item in action_list:
                                # Enhance click actions with more element details
                                if 'click' in action_item:
                                    # Add element type and purpose if available from observation
                                    if 'observation' in step:
                                        action_item['click']['element_type'] = _extract_element_type(step['observation'])
                                        action_item['click']['element_purpose'] = _extract_element_purpose(step['observation'])
                                
                                # Enhance type actions with field information
                                elif 'type' in action_item:
                                    if 'observation' in step:
                                        action_item['type']['field_type'] = _extract_field_type(step['observation'])
                                        action_item['type']['field_purpose'] = _extract_field_purpose(step['observation'])
                
                # Write the updated history data back to the file
                with open(history_file, 'w') as f:
                    json.dump(history_data, f, indent=2)
                    
                # Generate Cypress test for this history file
                from src.utils.cypress_generator import generate_cypress_test
                cypress_test_path = generate_cypress_test(history_file)
                logger.info(f"Generated Cypress test: {cypress_test_path}")
            except Exception as e:
                logger.error(f"Error updating history file with enhanced data: {str(e)}")

        final_result = history.final_result()
        errors = history.errors()
        model_actions = history.model_actions()
        model_thoughts = history.model_thoughts()

        trace_file = get_latest_files(save_trace_path)        

        return final_result, errors, model_actions, model_thoughts, trace_file.get('.zip'), history_file
    except Exception as e:
        import traceback
        traceback.print_exc()
        errors = str(e) + "\n" + traceback.format_exc()
        return '', errors, '', '', None, None
    finally:
        _global_agent = None
        # Handle cleanup based on persistence configuration
        if not keep_browser_open:
            if _global_browser_context:
                await _global_browser_context.close()
                _global_browser_context = None

            if _global_browser:
                await _global_browser.close()
                _global_browser = None

async def run_with_stream(
    agent_type,
    llm_provider,
    llm_model_name,
    llm_num_ctx,
    llm_temperature,
    llm_base_url,
    llm_api_key,
    use_own_browser,
    keep_browser_open,
    headless,
    disable_security,
    window_w,
    window_h,
    save_recording_path,
    save_agent_history_path,
    save_trace_path,
    enable_recording,
    task,
    add_infos,
    max_steps,
    use_vision,
    max_actions_per_step,
    tool_calling_method,
    chrome_cdp
):
    global _global_agent_state
    stream_vw = 80
    stream_vh = int(80 * window_h // window_w)
    if not headless:
        result = await run_browser_agent(
            agent_type=agent_type,
            llm_provider=llm_provider,
            llm_model_name=llm_model_name,
            llm_num_ctx=llm_num_ctx,
            llm_temperature=llm_temperature,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            use_own_browser=use_own_browser,
            keep_browser_open=keep_browser_open,
            headless=headless,
            disable_security=disable_security,
            window_w=window_w,
            window_h=window_h,
            save_recording_path=save_recording_path,
            save_agent_history_path=save_agent_history_path,
            save_trace_path=save_trace_path,
            enable_recording=enable_recording,
            task=task,
            add_infos=add_infos,
            max_steps=max_steps,
            use_vision=use_vision,
            max_actions_per_step=max_actions_per_step,
            tool_calling_method=tool_calling_method,
            chrome_cdp=chrome_cdp
        )
        # Add HTML content at the start of the result array
        html_content = f"<h1 style='width:{stream_vw}vw; height:{stream_vh}vh'>Using browser...</h1>"
        yield [html_content] + list(result)
    else:
        try:
            _global_agent_state.clear_stop()
            # Run the browser agent in the background
            agent_task = asyncio.create_task(
                run_browser_agent(
                    agent_type=agent_type,
                    llm_provider=llm_provider,
                    llm_model_name=llm_model_name,
                    llm_num_ctx=llm_num_ctx,
                    llm_temperature=llm_temperature,
                    llm_base_url=llm_base_url,
                    llm_api_key=llm_api_key,
                    use_own_browser=use_own_browser,
                    keep_browser_open=keep_browser_open,
                    headless=headless,
                    disable_security=disable_security,
                    window_w=window_w,
                    window_h=window_h,
                    save_recording_path=save_recording_path,
                    save_agent_history_path=save_agent_history_path,
                    save_trace_path=save_trace_path,
                    enable_recording=enable_recording,
                    task=task,
                    add_infos=add_infos,
                    max_steps=max_steps,
                    use_vision=use_vision,
                    max_actions_per_step=max_actions_per_step,
                    tool_calling_method=tool_calling_method,
                    chrome_cdp=chrome_cdp
                )
            )

            # Initialize values for streaming
            html_content = f"<h1 style='width:{stream_vw}vw; height:{stream_vh}vh'>Using browser...</h1>"
            final_result = errors = model_actions = model_thoughts = ""
            latest_videos = trace = history_file = None


            # Periodically update the stream while the agent task is running
            while not agent_task.done():
                try:
                    encoded_screenshot = await capture_screenshot(_global_browser_context)
                    if encoded_screenshot is not None:
                        html_content = f'<img src="data:image/jpeg;base64,{encoded_screenshot}" style="width:{stream_vw}vw; height:{stream_vh}vh ; border:1px solid #ccc;">'
                    else:
                        html_content = f"<h1 style='width:{stream_vw}vw; height:{stream_vh}vh'>Waiting for browser session...</h1>"
                except Exception as e:
                    html_content = f"<h1 style='width:{stream_vw}vw; height:{stream_vh}vh'>Waiting for browser session...</h1>"

                if _global_agent_state and _global_agent_state.is_stop_requested():
                    yield [
                        html_content,
                        final_result,
                        errors,
                        model_actions,
                        model_thoughts,
                        latest_videos,
                        trace,
                        history_file,
                        "Stopping...",  # stop_button
                        False,  # stop_button interactive
                        False,  # run_button interactive
                    ]
                    break
                else:
                    yield [
                        html_content,
                        final_result,
                        errors,
                        model_actions,
                        model_thoughts,
                        latest_videos,
                        trace,
                        history_file,
                        "Stop",  # Re-enable stop button
                        True,  # stop_button interactive
                        True  # Re-enable run button
                    ]
                await asyncio.sleep(0.05)

            # Once the agent task completes, get the results
            try:
                result = await agent_task
                final_result, errors, model_actions, model_thoughts, latest_videos, trace, history_file, stop_button_value, stop_button_interactive, run_button_interactive = result
            except Exception as e:
                errors = f"Agent error: {str(e)}"

            yield [
                html_content,
                final_result,
                errors,
                model_actions,
                model_thoughts,
                latest_videos,
                trace,
                history_file,
                "Stop",  # stop_button
                True,  # stop_button interactive
                True  # run_button interactive
            ]

        except Exception as e:
            import traceback
            yield [
                f"<h1 style='width:{stream_vw}vw; height:{stream_vh}vh'>Waiting for browser session...</h1>",
                "",
                f"Error: {str(e)}\n{traceback.format_exc()}",
                "",
                "",
                None,
                None,
                None,
                "Stop",  # Re-enable stop button
                True,  # stop_button interactive
                True    # Re-enable run button
            ]

async def close_global_browser():
    global _global_browser, _global_browser_context

    if _global_browser_context:
        await _global_browser_context.close()
        _global_browser_context = None

    if _global_browser:
        await _global_browser.close()
        _global_browser = None
        
async def run_deep_search(research_task, max_search_iteration_input, max_query_per_iter_input, llm_provider, llm_model_name, llm_num_ctx, llm_temperature, llm_base_url, llm_api_key, use_vision, use_own_browser, headless, chrome_cdp):
    from src.utils.deep_research import deep_research
    global _global_agent_state

    # Clear any previous stop request
    _global_agent_state.clear_stop()
    
    llm = utils.get_llm_model(
            provider=llm_provider,
            model_name=llm_model_name,
            num_ctx=llm_num_ctx,
            temperature=llm_temperature,
            base_url=llm_base_url,
            api_key=llm_api_key,
        )
    markdown_content, file_path = await deep_research(research_task, llm, _global_agent_state,
                                                        max_search_iterations=max_search_iteration_input,
                                                        max_query_num=max_query_per_iter_input,
                                                        use_vision=use_vision,
                                                        headless=headless,
                                                        use_own_browser=use_own_browser,
                                                        chrome_cdp=chrome_cdp
                                                        )
    
    return markdown_content, file_path, "Stop", True, True

def list_recordings(save_recording_path):
    if not os.path.exists(save_recording_path):
        return []

    # Get all video files
    recordings = glob.glob(os.path.join(save_recording_path, "*.[mM][pP]4")) + glob.glob(os.path.join(save_recording_path, "*.[wW][eE][bB][mM]"))

    # Sort recordings by creation time (oldest first)
    recordings.sort(key=os.path.getctime)

    # Add numbering to the recordings
    numbered_recordings = []
    for idx, recording in enumerate(recordings, start=1):
        filename = os.path.basename(recording)
        numbered_recordings.append((recording, f"{idx}. {filename}"))

    return numbered_recordings 

async def generate_cypress_test(history_file_path):
    """Generate a Cypress test script from an agent history file"""
    try:
        import sys
        import os
        
        # Add the current directory to the Python path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
            
        from src.utils.cypress_generator import CypressScriptGenerator
        
        # Create generator with default output directory
        generator = CypressScriptGenerator()
        
        # Generate the test script
        output_path = generator.generate_from_history(history_file_path)
        
        # Read the generated file to return its contents
        with open(output_path, 'r') as f:
            script_content = f.read()
            
        return script_content, output_path, ""  # Return content, path, and empty error
    except Exception as e:
        import traceback
        error_msg = f"Error generating Cypress test: {str(e)}\n{traceback.format_exc()}"
        return "", "", error_msg 

# Add helper methods for extracting element information
def _extract_element_type(observation):
    """Extract the type of element (button, link, etc.) from observation"""
    if not observation:
        return "unknown"
    
    # Try to determine element type from observation text
    observation_text = str(observation)
    if "button" in observation_text.lower():
        return "button"
    elif "link" in observation_text.lower() or "href" in observation_text.lower():
        return "link"
    elif "input" in observation_text.lower() or "field" in observation_text.lower():
        return "input"
    elif "select" in observation_text.lower() or "dropdown" in observation_text.lower():
        return "select"
    elif "checkbox" in observation_text.lower():
        return "checkbox"
    elif "radio" in observation_text.lower():
        return "radio"
    else:
        return "element"

def _extract_element_purpose(observation):
    """Extract the purpose of the element from observation"""
    if not observation:
        return ""
    
    # Try to determine element purpose from observation text
    observation_text = str(observation)
    
    # Look for common button/link purposes
    if "submit" in observation_text.lower():
        return "submit"
    elif "login" in observation_text.lower():
        return "login"
    elif "register" in observation_text.lower() or "sign up" in observation_text.lower():
        return "register"
    elif "search" in observation_text.lower():
        return "search"
    elif "add" in observation_text.lower():
        return "add"
    elif "delete" in observation_text.lower() or "remove" in observation_text.lower():
        return "delete"
    elif "edit" in observation_text.lower() or "update" in observation_text.lower():
        return "edit"
    else:
        return ""

def _extract_field_type(observation):
    """Extract the type of field from observation"""
    if not observation:
        return "text"
    
    observation_text = str(observation)
    if "password" in observation_text.lower():
        return "password"
    elif "email" in observation_text.lower():
        return "email"
    elif "number" in observation_text.lower():
        return "number"
    elif "date" in observation_text.lower():
        return "date"
    elif "search" in observation_text.lower():
        return "search"
    else:
        return "text"

def _extract_field_purpose(observation):
    """Extract the purpose of the field from observation"""
    if not observation:
        return ""
    
    observation_text = str(observation)
    if "username" in observation_text.lower():
        return "username"
    elif "password" in observation_text.lower():
        return "password"
    elif "email" in observation_text.lower():
        return "email"
    elif "search" in observation_text.lower():
        return "search"
    elif "first name" in observation_text.lower():
        return "first_name"
    elif "last name" in observation_text.lower():
        return "last_name"
    elif "address" in observation_text.lower():
        return "address"
    elif "phone" in observation_text.lower():
        return "phone"
    else:
        return ""