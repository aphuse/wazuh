/* Copyright (C) 2015-2021, Wazuh Inc.
 * All rights reserved.
 *
 * This program is free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation.
 */

#ifndef _REGISTER_HPP
#define _REGISTER_HPP

#include "builderTypes.hpp"
#include "registry.hpp"

// Add all builders includes here
#include <builders/assetBuilderDecoder.hpp>
#include <builders/assetBuilderFilter.hpp>
#include <builders/assetBuilderOutput.hpp>
#include <builders/assetBuilderRule.hpp>
#include <builders/combinatorBuilderBroadcast.hpp>
#include <builders/combinatorBuilderChain.hpp>
#include <builders/opBuilderARWrite.hpp>
#include <builders/opBuilderCondition.hpp>
#include <builders/opBuilderFileOutput.hpp>
#include <builders/opBuilderHelperFilter.hpp>
#include <builders/opBuilderHelperMap.hpp>
#include <builders/opBuilderKVDB.hpp>
#include <builders/opBuilderMap.hpp>
#include <builders/opBuilderMapReference.hpp>
#include <builders/opBuilderMapValue.hpp>
#include <builders/opBuilderSCAdecoder.hpp>
#include <builders/opBuilderWdbSync.hpp>
#include <builders/stageBuilderCheck.hpp>
#include <builders/stageBuilderNormalize.hpp>
#include <builders/stageBuilderOutputs.hpp>
#include <builders/stageParse.hpp>

namespace builder::internals
{
void registerBuilders()
{
    // Register all builders
    // Operations
    Registry::registerBuilder("map.value", builders::opBuilderMapValue);
    Registry::registerBuilder("map.reference", builders::opBuilderMapReference);
    Registry::registerBuilder("file", builders::opBuilderFileOutput);
    // Auxiliary
    Registry::registerBuilder("middle.condition", builders::middleBuilderCondition);
    Registry::registerBuilder("condition", builders::opBuilderCondition);
    Registry::registerBuilder("map", builders::opBuilderMap);
    // Helpers
    // TODO : Separate helpers in filters and maps
    Registry::registerBuilder("middle.helper.exists", builders::opBuilderHelperExists);
    Registry::registerBuilder("middle.helper.not_exists",
                              builders::opBuilderHelperNotExists);
    Registry::registerBuilder("middle.helper.s_le", builders::opBuilderHelperStringLE);
    Registry::registerBuilder("middle.helper.s_lt", builders::opBuilderHelperStringLT);
    Registry::registerBuilder("middle.helper.s_ge", builders::opBuilderHelperStringGE);
    Registry::registerBuilder("middle.helper.s_gt", builders::opBuilderHelperStringGT);
    Registry::registerBuilder("middle.helper.s_eq", builders::opBuilderHelperStringEq);
    Registry::registerBuilder("middle.helper.s_ne", builders::opBuilderHelperStringNE);
    Registry::registerBuilder("middle.helper.s_starts",
                              builders::opBuilderHelperStringStarts);
    Registry::registerBuilder("helper.s_up", builders::opBuilderHelperStringUP);
    Registry::registerBuilder("helper.s_lo", builders::opBuilderHelperStringLO);
    Registry::registerBuilder("helper.s_trim", builders::opBuilderHelperStringTrim);
    Registry::registerBuilder("helper.s_concat", builders::opBuilderHelperStringConcat);
    Registry::registerBuilder("middle.helper.i_le",
                              builders::opBuilderHelperIntLessThanEqual);
    Registry::registerBuilder("middle.helper.i_lt", builders::opBuilderHelperIntLessThan);
    Registry::registerBuilder("middle.helper.i_ge",
                              builders::opBuilderHelperIntGreaterThanEqual);
    Registry::registerBuilder("middle.helper.i_gt",
                              builders::opBuilderHelperIntGreaterThan);
    Registry::registerBuilder("middle.helper.i_eq", builders::opBuilderHelperIntEqual);
    Registry::registerBuilder("middle.helper.i_ne", builders::opBuilderHelperIntNotEqual);
    Registry::registerBuilder("helper.i_calc", builders::opBuilderHelperIntCalc);
    Registry::registerBuilder("helper.delete_field",
                              builders::opBuilderHelperDeleteField);
    Registry::registerBuilder("middle.helper.r_match",
                              builders::opBuilderHelperRegexMatch);
    Registry::registerBuilder("middle.helper.r_not_match",
                              builders::opBuilderHelperRegexNotMatch);
    Registry::registerBuilder("middle.helper.r_ext",
                              builders::opBuilderHelperRegexExtract);
    Registry::registerBuilder("middle.helper.ip_cidr", builders::opBuilderHelperIPCIDR);
    // KVDB Helpers
    Registry::registerBuilder("helper.kvdb_extract", builders::opBuilderKVDBExtract);
    Registry::registerBuilder("helper.kvdb_match", builders::opBuilderKVDBMatch);
    Registry::registerBuilder("helper.kvdb_notmatch", builders::opBuilderKVDBNotMatch);
    // DB sync
    Registry::registerBuilder("helper.wdb_query", builders::opBuilderWdbSyncQuery);
    Registry::registerBuilder("helper.wdb_update", builders::opBuilderWdbSyncUpdate);
    Registry::registerBuilder("helper.ar_write", builders::opBuilderARWrite);
    // SCA Decoder
    Registry::registerBuilder("helper.sca_decoder", builders::opBuilderSCAdecoder);
    // Combinators
    Registry::registerBuilder("combinator.chain", builders::combinatorBuilderChain);
    Registry::registerBuilder("combinator.broadcast",
                              builders::combinatorBuilderBroadcast);
    // Stages
    Registry::registerBuilder("check", builders::stageBuilderCheck);
    Registry::registerBuilder("allow", builders::stageBuilderCheck);
    Registry::registerBuilder("parse", builders::stageBuilderParse);
    Registry::registerBuilder("normalize", builders::stageBuilderNormalize);
    Registry::registerBuilder("outputs", builders::stageBuilderOutputs);
    // Assets
    Registry::registerBuilder("decoder", builders::assetBuilderDecoder);
    Registry::registerBuilder("filter", builders::assetBuilderFilter);
    Registry::registerBuilder("rule", builders::assetBuilderRule);
    Registry::registerBuilder("output", builders::assetBuilderOutput);
}
} // namespace builder::internals

#endif // _REGISTER_HPP
